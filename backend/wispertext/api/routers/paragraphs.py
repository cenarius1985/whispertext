"""Rutas de párrafos: listado del lector, audio y síntesis on-demand."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from wispertext.api.deps import get_arq, get_session
from wispertext.api.routers.documents import media_url
from wispertext.api.schemas import ParagraphOut
from wispertext.models import AudioAsset, Document, Image, Paragraph, ParagraphAudio
from wispertext.worker.tts import TTSError  # noqa: F401 — reexport informativo

router = APIRouter(tags=["paragraphs"])


def _uuid(value: str):
    import uuid as _u

    try:
        return _u.UUID(value)
    except ValueError:
        raise HTTPException(400, "id inválido")


async def _audio_route(session, paragraph_id) -> str | None:
    row = (
        await session.execute(
            select(AudioAsset.ruta)
            .join(ParagraphAudio, ParagraphAudio.audio_id == AudioAsset.id)
            .where(ParagraphAudio.paragraph_id == paragraph_id)
            .order_by(AudioAsset.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


@router.get("/api/documents/{doc_id}/paragraphs", response_model=list[ParagraphOut])
async def list_paragraphs(doc_id: str, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, _uuid(doc_id))
    if doc is None:
        raise HTTPException(404, "documento no existe")
    paragraphs = (
        (
            await session.execute(
                select(Paragraph)
                .options(selectinload(Paragraph.imagen))
                .where(Paragraph.document_id == doc.id, Paragraph.activo.is_(True))
                .order_by(Paragraph.indice)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for p in paragraphs:
        audio_ruta = await _audio_route(session, p.id) if p.estado_audio == "ready" else None
        imagen_ruta = p.imagen.ruta if p.imagen else None
        out.append(
            ParagraphOut(
                id=p.id,
                indice=p.indice,
                pagina=p.pagina,
                tipo=p.tipo,
                texto=p.texto_normalizado or p.texto_original,
                latex=p.texto_latex or None,
                estado_audio=p.estado_audio,
                skip_reason=p.skip_reason,
                audio_url=media_url(audio_ruta),
                imagen_url=media_url(imagen_ruta),
            )
        )
    return out


@router.get("/api/paragraphs/{paragraph_id}/audio")
async def get_paragraph_audio(paragraph_id: str, session: AsyncSession = Depends(get_session)):
    p = await session.get(Paragraph, _uuid(paragraph_id))
    if p is None:
        raise HTTPException(404, "párrafo no existe")
    ruta = await _audio_route(session, p.id)
    if ruta is None:
        raise HTTPException(409, "audio aún no disponible")
    from fastapi.responses import FileResponse as FR

    return FR(ruta, media_type="audio/mpeg", filename=f"parrafo_{p.indice}.mp3")


@router.post("/api/paragraphs/{paragraph_id}/synthesize", status_code=202)
async def synthesize_on_demand(
    paragraph_id: str,
    session: AsyncSession = Depends(get_session),
    arq=Depends(get_arq),
):
    """Encola la síntesis de un solo párrafo (el usuario está por escucharlo)."""
    p = await session.get(Paragraph, _uuid(paragraph_id))
    if p is None:
        raise HTTPException(404, "párrafo no existe")
    if p.estado_audio in ("ready", "skipped"):
        return {"estado": p.estado_audio}
    await arq.enqueue_job("synthesize_paragraph_task", str(p.id))
    return {"estado": "queued"}
