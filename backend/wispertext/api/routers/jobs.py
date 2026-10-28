"""Estado de jobs: polling del frontend (export con diálogo de descarga)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from wispertext.api.deps import get_session
from wispertext.api.schemas import JobOut
from wispertext.models import Job

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(400, "id inválido")
    job = await session.get(Job, jid)
    if job is None:
        raise HTTPException(404, "job no existe")
    return job
