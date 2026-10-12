"""Watchdog: reanuda automáticamente ingestas/síntesis interrumpidas.

Sin esto, un job que muere (timeout de arq, crash del worker, cola de Redis
perdida) deja el documento en su estado intermedio hasta que alguien lo
retome a mano — una tesis de ~1600 párrafos puede morir varias veces.

Corre en el arranque del worker y luego cada 5 min (cron de arq; con
max_jobs=1 el cron solo obtiene slot cuando no hay trabajo, justo cuando
un job muerto deja el worker libre). Para cada documento en estado
intermedio decide según su job más reciente:

- job vivo (running y avanzando, o queued reciente) → no tocar;
- job muerto (error, o running/queued sin avanzar > STALE_MIN) →
  * synthesizing con párrafos pendientes → re-encolar la síntesis
    (los párrafos ready no se rehacen; los de TTS fallido se reintentan);
  * synthesizing sin pendientes → cerrar como ready (murió al final);
  * extracting/cleaning → error visible (no se puede reanudar sin re-subir);
  * tras MAX_FALLOS errores reales → error visible (no insistir).

Las cancelaciones por job_timeout ("cancelado: ...") no cuentan como fallo:
reanudar es seguro porque cada párrafo terminado ya está persistido.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from wispertext.db import get_sessionmaker
from wispertext.models import Document, Job, Paragraph

log = logging.getLogger("wispertext.watchdog")

STALE_MIN = 15  # un párrafo tarda <60 s: 15 min sin avance = job muerto
MAX_FALLOS = 3  # errores reales (cancelaciones por timeout no cuentan)
INTERMEDIOS = ("extracting", "cleaning", "synthesizing")
_ERROR_CANCELADO = "cancelado%"  # prefijo del mensaje de _fail_cancelled


def _plan(
    doc_estado: str | None,
    job_estado: str | None,
    job_stale_min: float,
    fallos_reales: int,
    pendientes: int,
    arranque: bool = False,
) -> str | None:
    """Decisión pura, sin BD (testeable): None|'reanudar'|'ready'|'error'.

    `arranque=True` (inicio del worker): un job 'running' es siempre huérfano
    — nadie está ejecutando nada todavía; los 'queued' pueden seguir vivos
    en Redis y se ejecutarán solos.
    """
    if doc_estado not in INTERMEDIOS:
        return None
    job_muerto = (
        job_estado is None
        or job_estado == "error"
        or (job_estado in ("running", "queued") and job_stale_min > STALE_MIN)
        or (arranque and job_estado == "running")
    )
    if not job_muerto:
        return None
    if fallos_reales >= MAX_FALLOS:
        return "error"
    if doc_estado == "synthesizing":
        return "ready" if pendientes == 0 else "reanudar"
    return "error"


async def procesar_docs_huerfanos(redis, arranque: bool = False) -> list[str]:
    """Aplica _plan sobre cada documento en estado intermedio.

    Devuelve la lista de acciones tomadas (p. ej. ["reanudar <doc_id>"]).
    `redis` es la ArqRedis del worker (ctx["redis"]) para encolar jobs.
    `arranque=True` al iniciar el worker: un job 'running' es huérfano
    aunque su updated_at sea reciente (murió con el proceso).
    """
    acciones: list[str] = []
    sm = get_sessionmaker()
    ahora = datetime.now(timezone.utc)
    async with sm() as session:
        docs = (
            (
                await session.execute(
                    select(Document).where(Document.estado.in_(INTERMEDIOS))
                )
            )
            .scalars()
            .all()
        )
        for doc in docs:
            job = (
                (
                    await session.execute(
                        select(Job)
                        .where(Job.document_id == doc.id)
                        .order_by(Job.created_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            fallos_reales = (
                await session.execute(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.document_id == doc.id,
                        Job.estado == "error",
                        Job.error.notlike(_ERROR_CANCELADO),
                    )
                )
            ).scalar_one()
            pendientes = (
                await session.execute(
                    select(func.count())
                    .select_from(Paragraph)
                    .where(
                        Paragraph.document_id == doc.id,
                        Paragraph.activo.is_(True),
                        Paragraph.estado_audio.in_(("pending", "error")),
                    )
                )
            ).scalar_one()
            stale_min = (
                (ahora - job.updated_at).total_seconds() / 60
                if job is not None and job.updated_at is not None
                else float("inf")
            )
            plan = _plan(doc.estado, job.estado if job else None, stale_min,
                         fallos_reales, pendientes, arranque=arranque)

            if plan is None:
                continue
            if plan == "ready":
                doc.estado = "ready"
                await session.commit()
                acciones.append(f"ready {doc.id}")
                log.info("watchdog: %s sintetizado por completo → ready", doc.id)
            elif plan == "error":
                doc.estado = "error"
                doc.error = (
                    f"reintentos agotados ({fallos_reales} fallos)"
                    if fallos_reales >= MAX_FALLOS
                    else "interrumpido: el job murió sin poder reanudarse"
                )
                await session.commit()
                acciones.append(f"error {doc.id}")
                log.warning("watchdog: %s → error (%s)", doc.id, doc.error)
            elif plan == "reanudar":
                # los párrafos con TTS fallido se reintegran al lote
                await session.execute(
                    update(Paragraph)
                    .where(
                        Paragraph.document_id == doc.id,
                        Paragraph.activo.is_(True),
                        Paragraph.estado_audio == "error",
                    )
                    .values(estado_audio="pending")
                )
                nuevo = Job(
                    document_id=doc.id,
                    tipo="reprocess",
                    estado="queued",
                    detalle={"velocidad": doc.velocidad, "origen": "watchdog"},
                )
                session.add(nuevo)
                await session.flush()
                await session.commit()
                acciones.append(f"reanudar {doc.id}")
                log.warning(
                    "watchdog: reanudando %s (pendientes=%d, fallos=%d, job %s %s)",
                    doc.id,
                    pendientes,
                    fallos_reales,
                    job.estado if job else "inexistente",
                    f"stale {stale_min:.0f} min" if job else "",
                )
                await redis.enqueue_job("run_reprocess", str(nuevo.id))
    if acciones:
        log.info("watchdog: %d acción(es): %s", len(acciones), ", ".join(acciones))
    return acciones


async def watchdog(ctx: dict) -> None:
    """Cron de arq: cada 5 min busca documentos huérfanos y los reanuda."""
    try:
        await procesar_docs_huerfanos(ctx["redis"])
    except Exception:  # noqa: BLE001
        log.exception("watchdog falló (se reintentará en el próximo ciclo)")
