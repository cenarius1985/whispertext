"""Entrypoint del worker ARQ (cola única, CPU-bound secuencial)."""

import logging

from arq.connections import RedisSettings

from wispertext.config import get_settings
from wispertext.worker.jobs import (
    run_export,
    run_ingest,
    run_reprocess,
    run_replace,
    synthesize_paragraph_task,
)
from wispertext.worker.voices import ensure_voices_downloaded


async def startup(ctx: dict) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Descarga idempotente de voces (primera ejecución) — ADR-001.
    # Un fallo de red NO tumba el worker: TTS marcará error por párrafo y
    # un reinicio reintenta la descarga.
    try:
        ensure_voices_downloaded()
    except Exception:  # noqa: BLE001
        log = logging.getLogger("wispertext.voices")
        log.exception("descarga de voces falló; se reintenta al reiniciar")


async def shutdown(ctx: dict) -> None:
    pass


class WorkerSettings:
    functions = (
        run_ingest,
        run_replace,
        run_reprocess,
        run_export,
        synthesize_paragraph_task,
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 1          # Piper/OCR son CPU-bound: secuencial por diseño
    job_timeout = 14_400  # 4 h para OCR largos
    keep_result = 3_600
