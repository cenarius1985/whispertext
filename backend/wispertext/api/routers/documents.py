"""Rutas de documentos: biblioteca, subida, reemplazo, reproceso, export."""

import shutil
import uuid
from pathlib import Path

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from wispertext.api.deps import get_arq, get_session, save_upload, FORMATO_POR_EXT
from wispertext.api.schemas import (
    CategoryRef,
    DocumentOut,
    DocumentUpdateIn,
    ExportIn,
    ExportOut,
    JobOut,
    ProgressIn,
    ReprocessIn,
)
from wispertext.config import get_settings
from wispertext.models import (
    AudioAsset,
    Category,
    Document,
    Export,
    Job,
    Paragraph,
    ParagraphAudio,
    ReadingProgress,
    Voice,
)
from wispertext.worker.musica import es_url_youtube

router = APIRouter(prefix="/api/documents", tags=["documents"])


def media_url(ruta: str | None) -> str | None:
    if not ruta:
        return None
    try:
        rel = Path(ruta).resolve().relative_to(
            Path(get_settings().media_dir).resolve()
        )
    except ValueError:
        return None
    return "/media/" + rel.as_posix()


def doc_to_out(
    doc: Document,
    progreso_indice: int | None = None,
    duracion_seg: float | None = None,
) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    return out.model_copy(
        update={
            "voz_clave": doc.voz.clave if doc.voz else None,
            "portada_url": media_url(doc.portada_ruta),
            "progreso_indice": progreso_indice,
            "duracion_total_seg": duracion_seg or 0.0,
            "categorias": [CategoryRef.model_validate(c) for c in doc.categories],
        }
    )


async def _progress_map(session) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ReadingProgress.document_id, Paragraph.indice).join(
                Paragraph, Paragraph.id == ReadingProgress.paragraph_id
            )
        )
    ).all()
    return {str(d): i for d, i in rows}


async def _duracion_map(session) -> dict[str, float]:
    """Suma de duración de audio por documento (párrafos activos)."""
    rows = (
        await session.execute(
            select(Paragraph.document_id, func.sum(AudioAsset.duracion_seg))
            .join(ParagraphAudio, ParagraphAudio.paragraph_id == Paragraph.id)
            .join(AudioAsset, AudioAsset.id == ParagraphAudio.audio_id)
            .where(Paragraph.activo.is_(True))
            .group_by(Paragraph.document_id)
        )
    ).all()
    return {str(d): float(s or 0) for d, s in rows}


# --------------------------------------------------------------------------- #

@router.post("", response_model=DocumentOut, status_code=201)
async def create_document(
    archivo: UploadFile = File(...),
    titulo: str | None = Query(default=None),
    voz_clave: str | None = Query(default=None),
    idioma_lectura: str = Query(default="es"),
    session: AsyncSession = Depends(get_session),
    arq: ArqRedis = Depends(get_arq),
):
    doc_key = uuid.uuid4().hex[:12]
    ruta, sha, _size = await save_upload(doc_key, archivo)

    voz = (
        await session.execute(
            select(Voice).where(
                Voice.clave == (voz_clave or get_settings().piper_voice_default)
            )
        )
    ).scalar_one_or_none()
    if voz is None:
        raise HTTPException(404, f"voz '{voz_clave}' no existe")

    # Dedup "modo WhatsApp" (RF-01 / ADR-005)
    dup = (
        await session.execute(
            select(Document).where(
                Document.archivo_hash == sha,
                Document.voz_id == voz.id,
                Document.idioma_lectura == idioma_lectura,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, detail={"message": "archivo ya existe", "document_id": str(dup.id)})

    doc = Document(
        titulo=(titulo or Path(archivo.filename or "Documento").stem)[:300],
        idioma_origen=idioma_lectura,
        idioma_lectura=idioma_lectura,
        voz_id=voz.id,
        estado="pending",
        archivo_original=ruta,
        archivo_hash=sha,
        formato=FORMATO_POR_EXT.get(
            Path(archivo.filename or "").suffix.lower(), "pdf"
        ),
    )
    session.add(doc)
    await session.flush()
    doc.voz = voz  # evita lazy load async en doc_to_out

    job = Job(document_id=doc.id, tipo="ingest", estado="queued", detalle={})
    session.add(job)
    await session.commit()

    await arq.enqueue_job("run_ingest", str(job.id))
    await session.refresh(doc)  # eager (selectin de categorías incluido)
    return doc_to_out(doc)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    q: str | None = Query(default=None),
    categoria_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(Document)
        .options(selectinload(Document.voz))
        .order_by(Document.updated_at.desc())
    )
    if categoria_id:
        stmt = stmt.join(
            Document.categories
        ).where(Category.id == _uuid(categoria_id))
    docs = (await session.execute(stmt)).scalars().all()
    progress = await _progress_map(session)
    duraciones = await _duracion_map(session)
    out = []
    for d in docs:
        if q:
            ql = f"%{q.lower()}%"
            hit_titulo = q.lower() in d.titulo.lower()
            if not hit_titulo:
                hit_texto = (
                    await session.execute(
                        select(func.count())
                        .select_from(Paragraph)
                        .where(
                            Paragraph.document_id == d.id,
                            Paragraph.activo.is_(True),
                            func.lower(Paragraph.texto_normalizado).like(ql),
                        )
                    )
                ).scalar()
                if not hit_texto:
                    continue
        out.append(
            doc_to_out(d, progress.get(str(d.id)), duraciones.get(str(d.id)))
        )
    return out


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = (
        await session.execute(
            select(Document)
            .options(selectinload(Document.voz))
            .where(Document.id == _uuid(doc_id))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "documento no existe")
    progress = await _progress_map(session)
    duraciones = await _duracion_map(session)
    return doc_to_out(doc, progress.get(str(doc.id)), duraciones.get(str(doc.id)))


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")

    settings = get_settings()
    media = Path(settings.media_dir)
    # Archivos propios del documento (los audios cacheados son compartidos)
    Path(doc.archivo_original).unlink(missing_ok=True)
    (media / "covers" / f"{doc.id}.png").unlink(missing_ok=True)
    for pattern in (f"{doc.id}_v*", f"{doc.id.hex[:8]}_*"):
        for f in (media / "pdfs").glob(pattern):
            f.unlink(missing_ok=True)
    for folder in (media / "images").glob(f"{doc.id}_v*"):
        shutil.rmtree(folder, ignore_errors=True)
    for f in (media / "exports").glob(f"{doc.id}_*"):
        f.unlink(missing_ok=True)

    await session.delete(doc)  # cascada: párrafos, imágenes, jobs, exports, progreso
    await session.commit()


@router.post("/{doc_id}/replace", response_model=JobOut, status_code=202)
async def replace_document(
    doc_id: str,
    archivo: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    arq: ArqRedis = Depends(get_arq),
):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")

    doc_key = f"{doc.id.hex[:8]}r{uuid.uuid4().hex[:6]}"
    ruta, sha, _size = await save_upload(doc_key, archivo)
    if sha == doc.archivo_hash:
        Path(ruta).unlink(missing_ok=True)
        raise HTTPException(400, "el archivo es idéntico al actual (nada que actualizar)")

    job = Job(
        document_id=doc.id,
        tipo="replace",
        estado="queued",
        detalle={"ruta": ruta, "hash": sha},
    )
    session.add(job)
    await session.commit()
    await arq.enqueue_job("run_replace", str(job.id))
    return job


@router.post("/{doc_id}/reprocess", response_model=JobOut, status_code=202)
async def reprocess_document(
    doc_id: str,
    opts: ReprocessIn,
    session: AsyncSession = Depends(get_session),
    arq: ArqRedis = Depends(get_arq),
):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")
    if opts.voz_clave:
        voz = (
            await session.execute(select(Voice).where(Voice.clave == opts.voz_clave))
        ).scalar_one_or_none()
        if voz is None:
            raise HTTPException(404, f"voz '{opts.voz_clave}' no existe")
    if not any([opts.voz_clave, opts.velocidad, opts.traducir, opts.idioma_lectura]):
        raise HTTPException(400, "nada que reprocesar: indica voz/velocidad/traducción")

    job = Job(document_id=doc.id, tipo="reprocess", estado="queued", detalle=opts.model_dump())
    session.add(job)
    await session.commit()
    await arq.enqueue_job("run_reprocess", str(job.id))
    return job


@router.post("/{doc_id}/export", response_model=JobOut, status_code=202)
async def export_document(
    doc_id: str,
    opts: ExportIn,
    session: AsyncSession = Depends(get_session),
    arq: ArqRedis = Depends(get_arq),
):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")
    if opts.formato != "mp3":
        raise HTTPException(400, "solo mp3 por ahora (M4B en P2)")
    con_musica = bool((opts.musica_url or "").strip())
    if con_musica and not es_url_youtube(opts.musica_url):
        raise HTTPException(400, "musica_url debe ser de youtube.com o youtu.be")

    export = Export(
        document_id=doc.id,
        formato="mp3m" if con_musica else opts.formato,
        estado="queued",
    )
    session.add(export)
    await session.flush()
    detalle = {"export_id": str(export.id)}
    if con_musica:
        detalle.update(
            musica_url=opts.musica_url.strip(),
            musica_volumen_db=opts.musica_volumen_db,
        )
    job = Job(
        document_id=doc.id,
        tipo="export_musica" if con_musica else "export",
        estado="queued",
        detalle=detalle,
    )
    session.add(job)
    await session.commit()
    await arq.enqueue_job(
        "run_export_musica" if con_musica else "run_export", str(job.id)
    )
    return job


@router.get("/{doc_id}/exports", response_model=list[ExportOut])
async def list_exports(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")
    exports = (
        (
            await session.execute(
                select(Export)
                .where(Export.document_id == doc.id)
                .order_by(Export.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        ExportOut.model_validate(e).model_copy(
            update={"download_url": f"/api/exports/{e.id}/download" if e.estado == "done" else None}
        )
        for e in exports
    ]


@router.post("/{doc_id}/cover", response_model=DocumentOut)
async def upload_cover(
    doc_id: str,
    imagen: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    doc = (
        await session.execute(
            select(Document)
            .options(selectinload(Document.voz))
            .where(Document.id == _uuid(doc_id))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "documento no existe")
    if (imagen.filename or "").lower().rsplit(".", 1)[-1] not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(415, "portada debe ser png/jpg/webp")

    ext = (imagen.filename or "x.png").lower().rsplit(".", 1)[-1]
    covers = Path(get_settings().media_dir) / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    dest = covers / f"{doc.id}_custom.{ext}"
    dest.write_bytes(await imagen.read())
    doc.portada_ruta = str(dest)
    doc.portada_tipo = "upload"
    await session.commit()
    await session.refresh(doc)  # ídem: onupdate de updated_at
    return doc_to_out(doc)


@router.patch("/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: str,
    body: DocumentUpdateIn,
    session: AsyncSession = Depends(get_session),
):
    """Edición de metadatos: título y/o categorías (reemplazo completo N:M)."""
    doc = (
        await session.execute(
            select(Document)
            .options(selectinload(Document.voz))
            .where(Document.id == _uuid(doc_id))
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "documento no existe")
    if body.titulo is None and body.category_ids is None:
        raise HTTPException(400, "nada que actualizar: indica titulo o category_ids")

    if body.titulo is not None:
        doc.titulo = body.titulo.strip()

    if body.category_ids is not None:
        cats: list[Category] = []
        if body.category_ids:
            rows = (
                await session.execute(
                    select(Category).where(Category.id.in_(body.category_ids))
                )
            ).scalars().all()
            if len(rows) != len(set(body.category_ids)):
                raise HTTPException(404, "alguna categoría no existe")
            cats = sorted(rows, key=lambda c: c.nombre)
        doc.categories = cats

    await session.commit()
    await session.refresh(doc)  # updated_at expira por onupdate (async-safe)
    progress = await _progress_map(session)
    duraciones = await _duracion_map(session)
    return doc_to_out(doc, progress.get(str(doc.id)), duraciones.get(str(doc.id)))


@router.patch("/{doc_id}/progress", status_code=204)
async def save_progress(
    doc_id: str,
    body: ProgressIn,
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")
    p = await session.get(Paragraph, body.paragraph_id)
    if p is None or p.document_id != doc.id:
        raise HTTPException(400, "párrafo no pertenece al documento")
    existing = await session.get(ReadingProgress, doc.id)
    if existing is None:
        session.add(ReadingProgress(document_id=doc.id, paragraph_id=p.id))
    else:
        existing.paragraph_id = p.id
    await session.commit()


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, "id inválido")
