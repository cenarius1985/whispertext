"""Voces disponibles y descarga de exports."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wispertext.api.deps import get_session
from wispertext.api.schemas import VoiceOut
from wispertext.models import Export, Voice

router = APIRouter(tags=["voices"])


@router.get("/api/voices", response_model=list[VoiceOut])
async def list_voices(session: AsyncSession = Depends(get_session)):
    voices = (
        (
            await session.execute(
                select(Voice)
                .where(Voice.activa.is_(True))
                .order_by(Voice.idioma, Voice.nombre)
            )
        )
        .scalars()
        .all()
    )
    return [VoiceOut.model_validate(v) for v in voices]


@router.get("/api/exports/{export_id}/download")
async def download_export(export_id: str, session: AsyncSession = Depends(get_session)):
    try:
        eid = uuid.UUID(export_id)
    except ValueError:
        raise HTTPException(400, "id inválido")
    export = await session.get(Export, eid)
    if export is None or export.estado != "done" or not export.ruta:
        raise HTTPException(404, "export no existe o no terminó")
    nombre = f"audiolibro_{export.document_id.hex[:8]}.mp3"
    return FileResponse(export.ruta, media_type="audio/mpeg", filename=nombre)
