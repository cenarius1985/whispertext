"""Esquemas Pydantic de la API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: UUID
    titulo: str
    autor: str | None = None
    idioma_origen: str
    idioma_lectura: str
    voz_clave: str | None = None
    velocidad: float
    estado: str
    version_actual: int
    total_parrafos_activos: int
    portada_url: str | None = None
    progreso_indice: int | None = None
    error: str | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ParagraphOut(BaseModel):
    id: UUID
    indice: int
    pagina: int
    tipo: str
    texto: str  # normalizado para mostrar
    latex: str | None = None  # ecuaciones reconstruidas por Bonsai (KaTeX)
    estado_audio: str
    skip_reason: str | None = None
    audio_url: str | None = None
    imagen_url: str | None = None

    model_config = {"from_attributes": True}


class ProgressIn(BaseModel):
    paragraph_id: UUID


class DocumentUpdateIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)


class ReprocessIn(BaseModel):
    voz_clave: str | None = None
    velocidad: float | None = Field(default=None, gt=0.25, le=2.5)
    traducir: bool = False
    usar_bonsai: bool = False
    idioma_lectura: str | None = None


class ExportIn(BaseModel):
    formato: str = "mp3"


class ExportOut(BaseModel):
    id: UUID
    formato: str
    estado: str
    ruta: str
    duracion_total_seg: float
    tamano_bytes: int
    download_url: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: UUID
    document_id: UUID | None = None
    tipo: str
    estado: str
    total: int
    hecho: int
    detalle: dict[str, Any] = {}
    error: str | None = None

    model_config = {"from_attributes": True}


class VoiceOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    idioma: str
    calidad: str
    es_default: bool

    model_config = {"from_attributes": True}
