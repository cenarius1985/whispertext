"""Entrypoint del worker ARQ (cola única, CPU-bound secuencial)."""

import logging

from arq import cron
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
from wispertext.worker.watchdog import procesar_docs_huerfanos, watchdog


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
    # Al arrancar no hay jobs en ejecución: los documentos en estado
    # intermedio son huérfanos de un crash → el watchdog decide si se
    # reanudan (síntesis con párrafos pendientes) o quedan en error visible.
    try:
        await procesar_docs_huerfanos(ctx["redis"], arranque=True)
    except Exception:  # noqa: BLE001
        logging.getLogger("wispertext.watchdog").exception(
            "recovery de estados huérfanos falló"
        )


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
    job_timeout = 43_200  # 12 h: la síntesis completa de una tesis (~1600
                          # párrafos) supera las 4 h; arq cancela con
                          # CancelledError, que escapa al `except Exception`
                          # de run_ingest y deja el documento huérfano
    keep_result = 3_600
    # Watchdog cada 5 min: reanuda síntesis interrumpidas (job muerto,
    # timeout, crash). Con max_jobs=1 solo obtiene slot cuando el worker
    # está libre, justo cuando hay un huérfano que atender.
    cron_jobs = [cron(watchdog, minute=set(range(0, 60, 5)))]
