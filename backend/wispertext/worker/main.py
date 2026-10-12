"""Entrypoint del worker ARQ (cola única, CPU-bound secuencial)."""

import logging

from arq.connections import RedisSettings
from sqlalchemy import update

from wispertext.config import get_settings
from wispertext.db import get_sessionmaker
from wispertext.models import Document, Job
from wispertext.worker.jobs import (
    run_export,
    run_ingest,
    run_reprocess,
    run_replace,
    synthesize_paragraph_task,
)
from wispertext.worker.voices import ensure_voices_downloaded


async def _recover_orphans() -> None:
    """Marca como error documentos/jobs quedados en estado intermedio.

    Al arrancar el worker no hay jobs en ejecución: cualquier documento en
    extracting/cleaning/synthesizing es huérfano de un crash previo (p. ej.
    un fallo de BD a mitad de la ingesta) y sin esto quedaría 'limpiando'
    para siempre (bug 2026-10-11). Los jobs encolados en Redis siguen vivos
    y reescribirán su estado al ejecutarse.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        docs = (
            await session.execute(
                update(Document)
                .where(Document.estado.in_(("extracting", "cleaning", "synthesizing")))
                .values(
                    estado="error",
                    error="interrumpido: el worker se reinició durante el proceso",
                )
            )
        ).rowcount
        jobs = (
            await session.execute(
                update(Job)
                .where(Job.estado == "running")
                .values(estado="error", error="interrumpido: reinicio del worker")
            )
        ).rowcount
        await session.commit()
    if docs or jobs:
        logging.getLogger("wispertext.worker").warning(
            "recovery: %d documento(s) y %d job(s) huérfanos marcados como error",
            docs,
            jobs,
        )


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
    # Estados huérfanos de crashes previos → error visible (bug 2026-10-11)
    try:
        await _recover_orphans()
    except Exception:  # noqa: BLE001
        logging.getLogger("wispertext.worker").exception(
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
    job_timeout = 14_400  # 4 h para OCR largos
    keep_result = 3_600
