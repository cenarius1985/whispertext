"""Configuración central de WISPER-TEXT (API y worker comparten imagen)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infraestructura
    database_url: str = (
        "postgresql+asyncpg://wispertext:wispertext@localhost:5432/wispertext"
    )
    redis_url: str = "redis://localhost:6379/0"

    # Almacenamiento (montados como volúmenes en docker)
    media_dir: Path = Path("./media")
    models_dir: Path = Path("./models")

    # Bonsai (LLM externo, fail-soft — ADR-003)
    bonsai_base_url: str = "http://host.docker.internal:4687/v1"
    bonsai_model: str = "ternary-bonsai-8b"
    bonsai_enabled: bool = True
    bonsai_timeout_s: float = 8.0
    # las fórmulas valen más espera: prompt+generación en CPU llevan ~15-40 s
    bonsai_formula_timeout_s: float = 90.0

    # TTS — Piper (ADR-001)
    piper_voice_default: str = "es_AR-daniela-high"
    piper_voices_extra: str = "en_US-lessac-high,en_US-ryan-high"
    tts_format: str = "mp3"
    tts_bitrate: str = "96k"

    # OCR (ADR-007)
    tesseract_langs: str = "spa+eng"

    # Export / misc (ADR-005: NORMALIZER_VERSION invalida caches controladamente)
    export_pause_ms: int = 600
    max_upload_mb: int = 200
    normalizer_version: str = "v7"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def voice_claves(self) -> list[str]:
        claves = [self.piper_voice_default] + [
            c.strip() for c in self.piper_voices_extra.split(",") if c.strip()
        ]
        return list(dict.fromkeys(claves))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
