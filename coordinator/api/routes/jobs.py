from pathlib import Path, PurePosixPath
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import get_db
from core.redis_client import get_redis
from core.scheduler import JobScheduler
from models.job import Job, JobStatus
from models.schemas import (
    JobCreate,
    JobListResponse,
    JobPriority,
    JobResponse,
    JobUpdate,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
settings = get_settings()


_DEFAULT_OUTPUT_DIR = "/media/output"
_OUTPUT_EXT_BY_TYPE = {
    "convert_video": "mp4",
    "extract_audio": "mp3",
    "thumbnail": "jpg",
    "extract_metadata": "json",
    "classify_output": "json",
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
    """Generate a default output path under /media/output.

    Includes the job_id so concurrent jobs against the same input file (or
    repeated submissions of the same dataset) cannot stomp on each other.
    """
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
    """Create a new job and enqueue it on the matching priority list."""
    params = dict(job_create.params or {})
    params.pop("output_path", None)

    job_id = uuid4()
    normalized_input = _normalize_input_path(job_create.input_path)
    output_path = _build_output_path(
        job_id, job_create.type.value, job_create.params or {}
    )

    priority_value = (
        job_create.priority.value
        if isinstance(job_create.priority, JobPriority)
        else (job_create.priority or JobPriority.normal.value)
    )

    job = Job(
        id=job_id,
        type=job_create.type,
        input_path=normalized_input,
        output_path=output_path,
        priority=priority_value,
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
    priority: Optional[str] = Query(None),
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
    if priority:
        query = query.where(Job.priority == priority)

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


@router.get("/{job_id}/result")
async def get_job_result(job_id: UUID, db: AsyncSession = Depends(get_db)):
    """Stream the produced artefact for a completed job.

    The enunciado calls for "permitir su descarga o consulta posterior"; this
    is the formal download endpoint that ties a job_id to its output file
    without exposing the shared volume layout to clients.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.completed:
        raise HTTPException(
            status_code=409,
            detail=f"Job not ready: status={job.status.value}",
        )

    if not job.output_path:
        raise HTTPException(status_code=404, detail="Job has no output_path")

    output_file = Path(job.output_path)
    if not output_file.exists() or not output_file.is_file():
        raise HTTPException(
            status_code=410,
            detail=f"Output artefact missing: {job.output_path}",
        )

    return FileResponse(
        path=str(output_file),
        filename=output_file.name,
        media_type="application/octet-stream",
    )


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
        if field == "priority" and isinstance(value, JobPriority):
            value = value.value
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
