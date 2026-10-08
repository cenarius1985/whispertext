"""SSE de progreso en tiempo real (GET /api/events?document_id=...)."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from wispertext.events import stream_events

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def events(document_id: str | None = None):
    gen = stream_events(document_id=document_id)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
