"""App FastAPI — WISPER-TEXT. Sin auth (uso local, ADR/seguridad del vault)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from wispertext.api.deps import close_arq
from wispertext.api.routers import (
    categories,
    documents,
    events,
    jobs,
    paragraphs,
    voices,
)
from wispertext.api.routers import settings as settings_router
from wispertext.config import get_settings
from wispertext.db import init_db

log = logging.getLogger("wispertext.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await init_db()
    yield
    await close_arq()


app = FastAPI(title="WISPER-TEXT API", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(categories.router)
app.include_router(settings_router.router)
app.include_router(paragraphs.router)
app.include_router(voices.router)
app.include_router(jobs.router)
app.include_router(events.router)

# /media: audio, portadas, imágenes (rutas registradas en BD; sin listing)
settings.media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
