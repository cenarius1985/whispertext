"""Eventos de progreso vía Redis pub/sub → SSE (canal único, filtrado por payload)."""

import asyncio
import json
from typing import AsyncIterator

import redis.asyncio as aioredis

from wispertext.config import get_settings

CHANNEL = "wispertext:events"


async def publish_event(payload: dict) -> None:
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await r.publish(CHANNEL, json.dumps(payload, default=str))
    finally:
        await r.aclose()


async def stream_events(document_id: str | None = None) -> AsyncIterator[str]:
    """Generador SSE. Filtra por document_id cuando se entrega."""
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        yield ": conectado\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(pubsub.get_message(timeout=15.0), timeout=16.0)
            except asyncio.TimeoutError:
                msg = None
            if msg is None or msg["type"] != "message":
                yield ": ping\n\n"  # heartbeat para mantener el stream
                continue
            try:
                data = json.loads(msg["data"])
            except (TypeError, ValueError):
                continue
            if document_id and str(data.get("document_id")) != str(document_id):
                continue
            yield f"data: {json.dumps(data, default=str)}\n\n"
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await r.aclose()
