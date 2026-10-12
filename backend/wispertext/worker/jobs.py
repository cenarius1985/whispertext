"""Orquestación de jobs: ingest / replace (diff) / reprocess / export / on-demand."""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select, update

from wispertext.config import get_settings
from wispertext.db import get_sessionmaker
from wispertext.events import publish_event
from wispertext.models import (
    AudioAsset,
    Document,
    Export,
    Image,
    Job,
    Paragraph,
    ParagraphAudio,
    ReadingProgress,
    Voice,
)
from wispertext.worker import cleaning, editorial, speakable
from wispertext.worker.bonsai import bonsai_formula, bonsai_is_editorial
from wispertext.worker.diffing import align_versions
from wispertext.worker.exporter import export_document_mp3
from wispertext.worker.extraction import RawBlock
from wispertext.worker.extractors import extract_any
from wispertext.worker.tts import TTSError, ensure_audio_for_paragraph

log = logging.getLogger("wispertext.jobs")


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

async def _job_event(job: Job, document_id=None) -> None:
    await publish_event(
        {
            "type": "job",
            "job_id": str(job.id),
            "document_id": str(document_id or job.document_id),
            "tipo": job.tipo,
            "estado": job.estado,
            "hecho": job.hecho,
            "total": job.total,
            "detalle": job.detalle,
        }
    )


async def _patch_job(session, job: Job, **fields) -> None:
    for k, v in fields.items():
        setattr(job, k, v)
    await session.commit()
    await _job_event(job)


async def _fail(session, job: Job, doc: Document | None, exc: Exception) -> None:
    log.exception("job %s falló", job.id)
    error = f"{type(exc).__name__}: {exc}"[:2000]
    try:
        # El fallo original deja la sesión en PendingRollbackError y las
        # instancias expiradas: rollback + refresh ANTES de escribir el error
        # (si no, el registro del fallo también explota y el documento queda
        # para siempre en su estado intermedio — bug 2026-10-11).
        await session.rollback()
        await session.refresh(job)
        if doc is not None:
            await session.refresh(doc)
    except Exception:  # noqa: BLE001
        log.exception("no se pudo registrar el fallo del job %s en la BD", job.id)
        return
    job.estado = "error"
    job.error = error
    if doc is not None:
        doc.estado = "error"
        doc.error = error
    await session.commit()
    await _job_event(job)


async def _fail_cancelled(session, job: Job, doc: Document | None) -> None:
    """arq cancela jobs al agotar job_timeout con CancelledError, que escapa
    de `except Exception` (BaseException): sin esto el documento queda
    huérfano en su estado intermedio hasta el próximo arranque del worker."""
    await _fail(session, job, doc, RuntimeError("cancelado: job_timeout de arq agotado"))
    raise asyncio.CancelledError


MAX_BONSAI_CALLS = 12  # tope por versión: Bonsai caído no frena la ingesta
MAX_BONSAI_FORMULAS = 60  # tope de ecuaciones a reconstruir por versión


def _formula_plausible(original_lineal: str, latex: str) -> bool:
    """Anti-alucinación: el LaTeX debe compartir algún token con el original."""
    import re as _re

    toks = [
        t
        for t in _re.findall(r"[A-Za-z]{2,}|\d+", original_lineal)
        if t.lower() not in {"de", "la", "el", "los", "las"}
    ]
    if not toks:
        return True
    latex_low = latex.lower()
    return any(t.lower() in latex_low for t in toks[:10])


def _is_dudoso_editorial(pagina: int, total_paginas: int) -> bool:
    """Bonsai solo se consulta en zona editorial (primeras/últimas páginas)."""
    return pagina <= 2 or (total_paginas > 4 and pagina >= total_paginas - 1)


def _build_paragraphs(
    doc: Document,
    version: int,
    bloques: list[RawBlock],
    total_paginas: int,
    bonsai_calls: list[int] | None = None,
) -> tuple[list[Paragraph], list[tuple[Paragraph, bytes]]]:
    """Convierte bloques crudos en filas Paragraph (sin tocar la BD)."""
    settings = get_settings()
    bonsai_calls = bonsai_calls if bonsai_calls is not None else [0]
    paragraphs: list[Paragraph] = []
    pending_images: list[tuple[Paragraph, bytes]] = []

    for idx, b in enumerate(bloques):
        norm = cleaning.normalize_for_tts(b.texto or "")
        p = Paragraph(
            document_id=doc.id,
            version=version,
            indice=idx,
            pagina=b.pagina,
            tipo=b.tipo,
            texto_original=cleaning.strip_control_chars(b.texto or "")[:20000],
            texto_normalizado=norm,
            idioma=doc.idioma_lectura,
        )
        if b.tipo == "codigo":
            # md/html: bloques de código y tablas markdown — se muestran en el
            # lector pero no se leen (RF-MF-04)
            p.estado_audio = "skipped"
            p.skip_reason = "codigo"
            paragraphs.append(p)
            continue
        if b.tipo == "figura":
            p.texto_hablado = speakable.prepare_speech(norm) if norm else ""
            p.hash_normalizado = (
                cleaning.paragraph_hash(norm, p.idioma, settings.normalizer_version)
                if norm
                else ""
            )
            if not norm:
                p.estado_audio = "skipped"
                p.skip_reason = "figura_sin_caption"
            if b.image_bytes:
                pending_images.append((p, b.image_bytes))
            paragraphs.append(p)
            continue

        if b.tipo == "ecuacion":
            # Bonsai reconstruye LaTeX (KaTeX en el lector) + lectura hablada.
            # Fail-soft: sin Bonsai queda la imagen fiel del render y se salta.
            rec = None
            if bonsai_calls[0] < MAX_BONSAI_FORMULAS:
                bonsai_calls[0] += 1
                rec = bonsai_formula(b.texto or "")
            if rec and rec.get("latex") and not _formula_plausible(
                b.texto or "", rec["latex"]
            ):
                rec = None  # alucinación descartada (p.ej. "E = mc^2" genérico)
            if rec and (rec.get("hablado") or rec.get("latex")):
                p.texto_latex = (rec.get("latex") or "")[:4000]
                p.texto_hablado = rec.get("hablado") or ""
                p.estado_audio = "pending" if p.texto_hablado else "skipped"
                if not p.texto_hablado:
                    p.skip_reason = "formula"
                p.hash_normalizado = cleaning.paragraph_hash(
                    norm or (b.texto or "-")[:100], p.idioma,
                    settings.normalizer_version,
                )
            else:
                p.estado_audio = "skipped"
                p.skip_reason = "formula"
            if b.image_bytes:
                pending_images.append((p, b.image_bytes))
            paragraphs.append(p)
            continue

        if cleaning.looks_like_junk(norm):
            p.estado_audio = "skipped"
            p.skip_reason = "vacio"
            paragraphs.append(p)
            continue

        is_ed, reason = editorial.classify_editorial(norm)
        if (
            not is_ed
            and bonsai_calls[0] < MAX_BONSAI_CALLS
            and _is_dudoso_editorial(b.pagina, total_paginas)
        ):
            bonsai_calls[0] += 1
            verdict = bonsai_is_editorial(norm, contexto=f"página {b.pagina}")
            if verdict is True:
                is_ed, reason = True, "bonsai"
        if is_ed:
            p.estado_audio = "skipped"
            p.skip_reason = reason
        else:
            p.texto_hablado = speakable.prepare_speech(norm)
            p.hash_normalizado = cleaning.paragraph_hash(
                norm, p.idioma, settings.normalizer_version
            )
        paragraphs.append(p)

    return paragraphs, pending_images


def _save_images(session, pending: list[tuple[Paragraph, bytes]], version: int) -> None:
    settings = get_settings()
    base = Path(settings.media_dir) / "images"
    for p, png in pending:
        folder = base / f"{p.document_id}_v{version}"
        folder.mkdir(parents=True, exist_ok=True)
        ruta = folder / f"{p.indice:04d}_p{p.pagina}_{uuid.uuid4().hex[:6]}.png"
        ruta.write_bytes(png)
        session.add(Image(paragraph_id=p.id, ruta=str(ruta), pagina=p.pagina))


async def _synth_loop(session, job: Job, doc: Document, paragraphs: list[Paragraph]) -> None:
    """Sintetiza la lista de párrafos actualizando avance y publicando eventos."""
    voice = await session.get(Voice, doc.voz_id)
    to_synth = [p for p in paragraphs if p.estado_audio == "pending"]
    job.total = len(to_synth)
    await _patch_job(session, job, estado="running")
    for i, p in enumerate(to_synth):
        try:
            await ensure_audio_for_paragraph(session, p, voice.clave, doc.velocidad)
        except TTSError as exc:
            log.warning("TTS error párrafo %s: %s", p.id, exc)
            p.estado_audio = "error"
            await session.commit()
        job.hecho = i + 1
        await session.commit()
        await publish_event(
            {
                "type": "paragraph_ready",
                "document_id": str(doc.id),
                "paragraph_id": str(p.id),
                "indice": p.indice,
                "estado": p.estado_audio,
                "hecho": job.hecho,
                "total": job.total,
            }
        )


# --------------------------------------------------------------------------- #
# Jobs principales (tareas ARQ)
# --------------------------------------------------------------------------- #

async def run_ingest(ctx, job_id: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        doc = await session.get(Document, job.document_id)
        try:
            await _patch_job(session, job, estado="running")
            doc.estado = "extracting"
            await session.commit()

            ex = extract_any(doc.archivo_original)
            if ex.titulo_documento:
                doc.titulo = cleaning.strip_control_chars(ex.titulo_documento)[:300]
            if ex.autor and not doc.autor:
                doc.autor = cleaning.strip_control_chars(ex.autor)

            # Portada fallback: página 1 del PDF (RF-07 / M-5)
            if doc.portada_tipo != "upload" and ex.cover_png:
                covers = Path(get_settings().media_dir) / "covers"
                covers.mkdir(parents=True, exist_ok=True)
                cover_path = covers / f"{doc.id}.png"
                cover_path.write_bytes(ex.cover_png)
                doc.portada_ruta = str(cover_path)
                doc.portada_tipo = "pdf_page"

            doc.estado = "cleaning"
            await session.commit()
            paragraphs, pending_imgs = _build_paragraphs(doc, 1, ex.bloques, ex.num_paginas)
            session.add_all(paragraphs)
            await session.flush()
            _save_images(session, pending_imgs, 1)
            doc.total_parrafos_activos = len(paragraphs)
            doc.estado = "synthesizing"
            await session.commit()

            await _synth_loop(session, job, doc, paragraphs)

            doc.estado = "ready"
            doc.error = None
            job.detalle = {
                "parrafos": len(paragraphs),
                "ocr_paginas": ex.paginas_ocr,
                "version": 1,
            }
            await _patch_job(session, job, estado="done")
        except Exception as exc:  # noqa: BLE001
            await _fail(session, job, doc, exc)
        except asyncio.CancelledError:
            await _fail_cancelled(session, job, doc)


async def run_replace(ctx, job_id: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        doc = await session.get(Document, job.document_id)
        try:
            await _patch_job(session, job, estado="running")
            nueva_ruta = job.detalle.get("ruta")
            nuevo_hash = job.detalle.get("hash")
            old_version = doc.version_actual
            new_version = old_version + 1

            doc.estado = "extracting"
            await session.commit()
            ex = extract_any(nueva_ruta)
            if ex.titulo_documento:
                doc.titulo = cleaning.strip_control_chars(ex.titulo_documento)[:300]

            doc.estado = "cleaning"
            await session.commit()
            new_paragraphs, pending_imgs = _build_paragraphs(
                doc, new_version, ex.bloques, ex.num_paginas
            )

            # Diff contra la versión anterior (RF-11 / ADR-005)
            old_paragraphs = (
                (
                    await session.execute(
                        select(Paragraph)
                        .where(
                            Paragraph.document_id == doc.id,
                            Paragraph.version == old_version,
                        )
                        .order_by(Paragraph.indice)
                    )
                )
                .scalars()
                .all()
            )
            old_hashes = [p.hash_normalizado for p in old_paragraphs]
            new_hashes = [p.hash_normalizado for p in new_paragraphs]
            diff = align_versions(old_hashes, new_hashes)

            # Portada de la nueva versión (si no es subida por el usuario)
            if doc.portada_tipo == "pdf_page" and ex.cover_png:
                covers = Path(get_settings().media_dir) / "covers"
                cover_path = covers / f"{doc.id}.png"
                cover_path.write_bytes(ex.cover_png)
                doc.portada_ruta = str(cover_path)

            session.add_all(new_paragraphs)
            await session.flush()
            _save_images(session, pending_imgs, new_version)

            # diff.reused maneja POSICIONES de lista (no Paragraph.indice)
            for old_idx, new_idx in diff.reused:
                old_p = old_paragraphs[old_idx]
                new_p = new_paragraphs[new_idx]
                assocs = (
                    (
                        await session.execute(
                            select(ParagraphAudio).where(
                                ParagraphAudio.paragraph_id == old_p.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for a in assocs:
                    session.add(
                        ParagraphAudio(paragraph_id=new_p.id, audio_id=a.audio_id)
                    )
                new_p.estado_audio = "ready" if assocs else new_p.estado_audio

            # Desactivar párrafos de la versión anterior
            await session.execute(
                update(Paragraph)
                .where(Paragraph.document_id == doc.id, Paragraph.version == old_version)
                .values(activo=False)
            )

            doc.version_actual = new_version
            doc.total_parrafos_activos = len(new_paragraphs)
            doc.archivo_original = nueva_ruta
            doc.archivo_hash = nuevo_hash
            doc.estado = "synthesizing"
            await session.commit()

            await _synth_loop(session, job, doc, new_paragraphs)

            # Remapear progreso de lectura al párrafo más cercano de la nueva versión
            prog = await session.get(ReadingProgress, doc.id)
            if prog is not None:
                antiguo = await session.get(Paragraph, prog.paragraph_id)
                if antiguo is not None and not antiguo.activo:
                    idx = min(
                        range(len(new_paragraphs)),
                        key=lambda i: abs(new_paragraphs[i].indice - antiguo.indice),
                        default=None,
                    )
                    if idx is not None:
                        prog.paragraph_id = new_paragraphs[idx].id

            doc.estado = "ready"
            job.detalle = {
                "version": new_version,
                "reutilizados": len(diff.reused),
                "sintetizados": len(diff.to_synth),
                "eliminados": len(diff.removed),
                "ahorro": round(diff.ahorro, 3),
                "ocr_paginas": ex.paginas_ocr,
            }
            await _patch_job(session, job, estado="done")
        except Exception as exc:  # noqa: BLE001
            await _fail(session, job, doc, exc)
        except asyncio.CancelledError:
            await _fail_cancelled(session, job, doc)


async def run_reprocess(ctx, job_id: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        doc = await session.get(Document, job.document_id)
        try:
            await _patch_job(session, job, estado="running")
            opts = job.detalle or {}

            if opts.get("voz_clave"):
                voz = (
                    await session.execute(
                        select(Voice).where(Voice.clave == opts["voz_clave"])
                    )
                ).scalar_one()
                doc.voz_id = voz.id
            if opts.get("velocidad"):
                doc.velocidad = float(opts["velocidad"])

            active = (
                (
                    await session.execute(
                        select(Paragraph)
                        .where(Paragraph.document_id == doc.id, Paragraph.activo.is_(True))
                        .order_by(Paragraph.indice)
                    )
                )
                .scalars()
                .all()
            )

            if opts.get("idioma_lectura"):
                doc.idioma_lectura = opts["idioma_lectura"]

            if opts.get("traducir"):
                doc.estado = "cleaning"
                await session.commit()
                for p in active:
                    if p.estado_audio == "skipped" or not p.texto_normalizado:
                        continue
                    try:
                        p.texto_hablado = speakable.translate(
                            p.texto_normalizado,
                            source=doc.idioma_origen,
                            target=doc.idioma_lectura,
                            use_bonsai=bool(opts.get("usar_bonsai")),
                        )
                        p.estado_audio = "pending"
                    except speakable.TranslationUnavailable as exc:
                        await _fail(session, job, doc, exc)
                        return

            doc.estado = "synthesizing"
            await session.commit()
            await _synth_loop(session, job, doc, active)

            doc.estado = "ready"
            await _patch_job(session, job, estado="done")
        except Exception as exc:  # noqa: BLE001
            await _fail(session, job, doc, exc)
        except asyncio.CancelledError:
            await _fail_cancelled(session, job, doc)


async def run_export(ctx, job_id: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        doc = await session.get(Document, job.document_id)
        export_id = job.detalle.get("export_id")
        export = await session.get(Export, export_id) if export_id else None
        try:
            await _patch_job(session, job, estado="running")
            if export:
                export.estado = "running"
                await session.commit()

            rows = (
                (
                    await session.execute(
                        select(Paragraph, AudioAsset)
                        .join(ParagraphAudio, ParagraphAudio.paragraph_id == Paragraph.id)
                        .join(AudioAsset, AudioAsset.id == ParagraphAudio.audio_id)
                        .where(Paragraph.document_id == doc.id, Paragraph.activo.is_(True))
                        .order_by(Paragraph.indice)
                    )
                )
                .all()
            )
            faltan = doc.total_parrafos_activos - len(rows)
            if faltan > 0:
                raise RuntimeError(
                    f"faltan {faltan} párrafos por sintetizar; espera a que termine"
                )

            out_dir = Path(get_settings().media_dir) / "exports"
            final, dur = export_document_mp3(doc, [a.ruta for _, a in rows], out_dir)

            if export:
                export.ruta = str(final)
                export.duracion_total_seg = dur
                export.tamano_bytes = final.stat().st_size
                export.estado = "done"
            job.detalle = {**job.detalle, "ruta": str(final), "duracion": dur}
            await _patch_job(session, job, estado="done")
        except Exception as exc:  # noqa: BLE001
            if export:
                export.estado = "error"
            await _fail(session, job, doc, exc)
        except asyncio.CancelledError:
            if export:
                export.estado = "error"
            await _fail_cancelled(session, job, doc)


async def synthesize_paragraph_task(ctx, paragraph_id: str) -> None:
    """Síntesis on-demand de un párrafo (prioridad del lector)."""
    sm = get_sessionmaker()
    async with sm() as session:
        p = await session.get(Paragraph, paragraph_id)
        if p is None or p.estado_audio in ("ready", "skipped"):
            return
        doc = await session.get(Document, p.document_id)
        voice = await session.get(Voice, doc.voz_id)
        try:
            await ensure_audio_for_paragraph(session, p, voice.clave, doc.velocidad)
        except TTSError as exc:
            log.warning("on-demand %s: %s", paragraph_id, exc)
            p.estado_audio = "error"
            await session.commit()
        await publish_event(
            {
                "type": "paragraph_ready",
                "document_id": str(doc.id),
                "paragraph_id": str(p.id),
                "indice": p.indice,
                "estado": p.estado_audio,
                "on_demand": True,
            }
        )
