from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from uuid import UUID
from typing import Optional

from core.database import get_db
from core.redis_client import get_redis
from core.scheduler import JobScheduler
from core.config import get_settings
from models.job import Job, JobStatus
from models.schemas import (
    JobCreate,
    JobResponse,
    JobListResponse,
    JobUpdate,
)
from pathlib import PurePosixPath
from uuid import uuid4

router = APIRouter(prefix="/jobs", tags=["jobs"])
settings = get_settings()


_DEFAULT_OUTPUT_DIR = "/media/output"
_OUTPUT_EXT_BY_TYPE = {
    "convert_video": "mp4",
    "extract_audio": "mp3",
    "thumbnail": "jpg",
}


def _normalize_input_path(raw: str) -> str:
    """Map a client-side path (possibly Windows-flavoured) to a container path
    under /media/input so workers can read it."""
    if not raw:
        return raw
    if raw.startswith("/media/"):
        return raw
    basename = PurePosixPath(raw.replace("\\", "/")).name
    return f"/media/input/{basename}"


def _build_output_path(job_id, job_type: str, params: dict) -> str:
    """Generate a default output path under /media/output."""
    if isinstance(params, dict):
        explicit = params.get("output_path")
        if isinstance(explicit, str) and explicit:
            return explicit
    ext = _OUTPUT_EXT_BY_TYPE.get(job_type, "out")
    if job_type == "convert_video" and isinstance(params, dict):
        fmt = params.get("format")
        if isinstance(fmt, str) and fmt:
            ext = fmt
    return f"{_DEFAULT_OUTPUT_DIR}/{job_id}.{ext}"


@router.post("", response_model=JobResponse)
async def create_job(
    job_create: JobCreate,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Create a new job and enqueue it"""
    params = dict(job_create.params or {})
    params.pop("output_path", None)

    job_id = uuid4()
    normalized_input = _normalize_input_path(job_create.input_path)
    output_path = _build_output_path(job_id, job_create.type.value, job_create.params or {})

    job = Job(
        id=job_id,
        type=job_create.type,
        input_path=normalized_input,
        output_path=output_path,
        params=params,
    )

    db.add(job)
    await db.flush()

    scheduler = JobScheduler(redis, settings.redis_queue_key)
    success = await scheduler.enqueue_job(db, job)

    if not success:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to enqueue job")

    await db.commit()
    await db.refresh(job)

    return job


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(None),
    worker_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters"""
    query = select(Job).order_by(desc(Job.created_at))

    if status:
        query = query.where(Job.status == status)
    if worker_id:
        query = query.where(Job.worker_id == worker_id)

    result = await db.execute(query.offset(offset).limit(limit))
    jobs = result.scalars().all()

    total_result = await db.execute(select(Job))
    total = len(total_result.scalars().all())

    return JobListResponse(total=total, jobs=jobs)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get details of a specific job"""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: UUID,
    job_update: JobUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update job details"""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    update_data = job_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    await db.commit()
    await db.refresh(job)

    return job


@router.delete("/{job_id}")
async def delete_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete/cancel a job (only if pending)"""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete job with status {job.status}",
        )

    await db.delete(job)
    await db.commit()

    return {"detail": "Job deleted"}
