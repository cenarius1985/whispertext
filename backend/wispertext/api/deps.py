"""Dependencias compartidas de la API (sesión, pool ARQ)."""

import hashlib
import re
from pathlib import Path

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from wispertext.config import get_settings
from wispertext.db import get_sessionmaker

_arq_pool: ArqRedis | None = None


async def get_session():
    async with get_sessionmaker()() as session:
        yield session


async def get_arq() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            RedisSettings.from_dsn(get_settings().redis_url)
        )
    return _arq_pool


async def close_arq() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.aclose()
        _arq_pool = None


ALLOWED_EXTENSIONS = {".pdf"}  # P2: .md, .txt, .docx, .epub


async def save_upload(doc_key: str, upload: UploadFile) -> tuple[str, str, int]:
    """Guarda el archivo subido y devuelve (ruta_absoluta, sha256, tamaño).

    Valida extensión y tamaño máximo; nombre saneado (RF path traversal).
    """
    settings = get_settings()
    nombre = upload.filename or "documento.pdf"
    ext = Path(nombre).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"tipo no permitido '{ext}' (solo PDF por ahora)")

    safe = re.sub(r"[^\w.\- ]", "_", nombre)[:120] or "documento.pdf"
    folder = Path(settings.media_dir) / "pdfs"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{doc_key}_{safe}"

    hasher = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as fh:
            while chunk := await upload.read(1 << 20):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, f"archivo > {settings.max_upload_mb} MB")
                fh.write(chunk)
                hasher.update(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    return str(dest.resolve()), hasher.hexdigest(), size
