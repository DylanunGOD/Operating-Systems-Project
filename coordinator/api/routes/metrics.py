from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from core.database import get_db
from core.redis_client import get_redis
from core.config import get_settings
from models.job import Job, Worker, JobStatus
from models.schemas import MetricsResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])
settings = get_settings()


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis),
):
    """Get system metrics and statistics"""
    try:
        queue_length = redis.llen(settings.redis_queue_key)
    except Exception:
        queue_length = 0

    result = await db.execute(select(func.count(Job.id)))
    jobs_total = result.scalar() or 0

    result = await db.execute(
        select(func.count(Job.id)).where(Job.status == JobStatus.completed)
    )
    jobs_completed = result.scalar() or 0

    result = await db.execute(
        select(func.count(Job.id)).where(Job.status == JobStatus.failed)
    )
    jobs_failed = result.scalar() or 0

    result = await db.execute(
        select(func.count(Job.id)).where(Job.status == JobStatus.processing)
    )
    jobs_processing = result.scalar() or 0

    result = await db.execute(select(func.count(Worker.id)))
    workers_total = result.scalar() or 0

    result = await db.execute(
        select(func.count(Worker.id)).where(Worker.status == "idle")
    )
    workers_idle = result.scalar() or 0

    workers_busy = workers_total - workers_idle
    workers_online = workers_total

    return MetricsResponse(
        queue_length=queue_length,
        jobs_total=jobs_total,
        jobs_completed=jobs_completed,
        jobs_failed=jobs_failed,
        jobs_processing=jobs_processing,
        workers_online=workers_online,
        workers_idle=workers_idle,
        workers_busy=workers_busy,
    )
