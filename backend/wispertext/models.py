"""Modelo SQLAlchemy — ver modelo de datos en el vault (02-base-de-datos)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    clave: Mapped[str] = mapped_column(String(64), unique=True)
    nombre: Mapped[str] = mapped_column(String(64))
    idioma: Mapped[str] = mapped_column(String(8))  # es_AR, en_US, ...
    calidad: Mapped[str] = mapped_column(String(8), default="high")
    ruta_onnx: Mapped[str] = mapped_column(Text)
    es_default: Mapped[bool] = mapped_column(Boolean, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Dedup "modo WhatsApp": mismo archivo + misma config → no reprocesar.
        UniqueConstraint("archivo_hash", "voz_id", "idioma_lectura", name="uq_dedup"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    titulo: Mapped[str] = mapped_column(Text)
    autor: Mapped[str | None] = mapped_column(Text, nullable=True)
    idioma_origen: Mapped[str] = mapped_column(String(8), default="es")
    idioma_lectura: Mapped[str] = mapped_column(String(8), default="es")
    voz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voices.id"))
    velocidad: Mapped[float] = mapped_column(Float, default=1.0)
    # pending | extracting | cleaning | synthesizing | ready | error
    estado: Mapped[str] = mapped_column(String(16), default="pending")
    archivo_original: Mapped[str] = mapped_column(Text)
    archivo_hash: Mapped[str] = mapped_column(String(64))
    version_actual: Mapped[int] = mapped_column(Integer, default=1)
    portada_ruta: Mapped[str | None] = mapped_column(Text, nullable=True)
    portada_tipo: Mapped[str] = mapped_column(String(12), default="ninguna")
    total_parrafos_activos: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    voz = relationship("Voice")
    paragraphs = relationship(
        "Paragraph",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,  # la BD hace ON DELETE CASCADE (async-safe)
    )


class Paragraph(Base):
    __tablename__ = "paragraphs"
    __table_args__ = (
        Index("ix_parrafos_doc_version_indice", "document_id", "version", "indice"),
        Index("ix_parrafos_hash", "hash_normalizado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    indice: Mapped[int] = mapped_column(Integer)
    pagina: Mapped[int] = mapped_column(Integer, default=1)
    tipo: Mapped[str] = mapped_column(String(12), default="texto")  # titulo|texto|figura
    texto_original: Mapped[str] = mapped_column(Text, default="")
    texto_normalizado: Mapped[str] = mapped_column(Text, default="")
    texto_hablado: Mapped[str] = mapped_column(Text, default="")
    # LaTeX reconstruido por Bonsai para ecuaciones (render KaTeX en el lector)
    texto_latex: Mapped[str] = mapped_column(Text, default="")
    hash_normalizado: Mapped[str] = mapped_column(String(64), default="")
    idioma: Mapped[str] = mapped_column(String(8), default="es")
    # pending | synthesizing | ready | error | skipped
    estado_audio: Mapped[str] = mapped_column(String(12), default="pending")
    skip_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document = relationship("Document", back_populates="paragraphs")
    imagen = relationship(
        "Image",
        uselist=False,
        back_populates="paragraph",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    audios = relationship(
        "ParagraphAudio", back_populates="paragraph", cascade="all, delete-orphan"
    )


class AudioAsset(Base):
    __tablename__ = "audio_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    # UNIQUE(hash_texto, voz, velocidad, formato) materializado como clave (ADR-005)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True)
    voz_clave: Mapped[str] = mapped_column(String(64))
    velocidad: Mapped[float] = mapped_column(Float, default=1.0)
    formato: Mapped[str] = mapped_column(String(8), default="mp3")
    ruta: Mapped[str] = mapped_column(Text)
    duracion_seg: Mapped[float] = mapped_column(Float, default=0.0)
    tamano_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParagraphAudio(Base):
    """N:M párrafo↔audio: el mismo MP3 (mismo hash) sirve a varias versiones/docs."""

    __tablename__ = "paragraphs_audio"

    paragraph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE"), primary_key=True
    )
    audio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("audio_assets.id"), primary_key=True
    )

    paragraph = relationship("Paragraph", back_populates="audios")
    audio = relationship("AudioAsset")


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    paragraph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE")
    )
    ruta: Mapped[str] = mapped_column(Text)
    pagina: Mapped[int] = mapped_column(Integer, default=1)
    ancho: Mapped[int] = mapped_column(Integer, default=0)
    alto: Mapped[int] = mapped_column(Integer, default=0)

    paragraph = relationship("Paragraph", back_populates="imagen")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(16))  # ingest|replace|reprocess|export
    estado: Mapped[str] = mapped_column(String(12), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    hecho: Mapped[int] = mapped_column(Integer, default=0)
    detalle: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    formato: Mapped[str] = mapped_column(String(8), default="mp3")
    ruta: Mapped[str] = mapped_column(Text, default="")
    duracion_total_seg: Mapped[float] = mapped_column(Float, default=0.0)
    tamano_bytes: Mapped[int] = mapped_column(Integer, default=0)
    estado: Mapped[str] = mapped_column(String(12), default="queued")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReadingProgress(Base):
    __tablename__ = "reading_progress"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    paragraph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
