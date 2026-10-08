"""Sesiones async de SQLAlchemy + inicialización (create_all + seed de voces)."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from wispertext.config import get_settings
from wispertext.models import Base, Voice

_engine = None
_sessionmaker = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def _voice_metadata(clave: str) -> tuple[str, str, str]:
    """'es_AR-daniela-high' -> ('Daniela', 'es_AR', 'high')."""
    region, nombre, calidad = clave.split("-")  # la región usa _ no -
    return nombre.capitalize(), region, calidad


def parse_voice_clave(clave: str) -> tuple[str, str, str, str]:
    """Clave Piper -> (nombre, idioma_region, calidad, idioma_base)."""
    nombre, region, calidad = _voice_metadata(clave)
    return nombre, region, calidad, region.split("_")[0]


async def init_db() -> None:
    settings = get_settings()
    for d in ("pdfs", "audio", "covers", "images", "exports"):
        (settings.media_dir / d).mkdir(parents=True, exist_ok=True)
    (settings.models_dir / "piper").mkdir(parents=True, exist_ok=True)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all no altera tablas existentes: columnas nuevas a mano
        from sqlalchemy import text

        await conn.execute(
            text("ALTER TABLE paragraphs ADD COLUMN IF NOT EXISTS texto_latex TEXT DEFAULT ''")
        )

    # Seed de voces según configuración (idempotente)
    sm = get_sessionmaker()
    async with sm() as session:
        existing = {
            v.clave: v
            for v in (await session.execute(select(Voice))).scalars().all()
        }
        default = settings.piper_voice_default
        for clave in settings.voice_claves:
            if clave in existing:
                continue
            nombre, region, calidad, _ = parse_voice_clave(clave)
            session.add(
                Voice(
                    clave=clave,
                    nombre=nombre,
                    idioma=region,
                    calidad=calidad,
                    ruta_onnx=str(
                        Path(settings.models_dir) / "piper" / f"{clave}.onnx"
                    ),
                    es_default=(clave == default),
                )
            )
        # Garantiza un único default si cambió la config
        for clave, v in existing.items():
            v.es_default = clave == default
        await session.commit()
