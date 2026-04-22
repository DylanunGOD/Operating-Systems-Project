from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Counter,
    Histogram,
    generate_latest,
)

from core.database import get_db
from core.redis_client import get_redis
from core.config import get_settings
from models.job import Job, Worker, JobStatus

router = APIRouter(prefix="/metrics", tags=["metrics"])
settings = get_settings()

# Create a dedicated registry for coordinator metrics
metrics_registry = CollectorRegistry()

# Define Prometheus metrics
coordinator_jobs_total = Gauge(
    "coordinator_jobs_total",
    "Total number of jobs by status",
    labelnames=["status"],
    registry=metrics_registry,
)

coordinator_workers_total = Gauge(
    "coordinator_workers_total",
    "Total number of workers by status",
    labelnames=["status"],
    registry=metrics_registry,
)

coordinator_queue_depth = Gauge(
    "coordinator_queue_depth",
    "Current depth of the Redis job queue",
    registry=metrics_registry,
)

coordinator_requests_total = Counter(
    "coordinator_requests_total",
    "Total HTTP requests",
    labelnames=["method", "path", "status_code"],
    registry=metrics_registry,
)

coordinator_request_duration_seconds = Histogram(
    "coordinator_request_duration_seconds",
    "Request latency in seconds",
    labelnames=["method", "path"],
    registry=metrics_registry,
)


@router.get("")
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Get Prometheus metrics in text format"""
    try:
        queue_length = redis.llen(settings.redis_queue_key)
    except Exception:
        queue_length = 0

    coordinator_queue_depth.set(queue_length)

    # Get job counts by status
    for status in JobStatus:
        result = await db.execute(
            select(func.count(Job.id)).where(Job.status == status)
        )
        count = result.scalar() or 0
        coordinator_jobs_total.labels(status=status.value).set(count)

    # Get worker counts by status
    result = await db.execute(select(func.count(Worker.id)))
    workers_total = result.scalar() or 0

    result = await db.execute(
        select(func.count(Worker.id)).where(Worker.status == "idle")
    )
    workers_idle = result.scalar() or 0

    workers_busy = workers_total - workers_idle
    workers_online = workers_total

    coordinator_workers_total.labels(status="online").set(workers_online)
    coordinator_workers_total.labels(status="offline").set(0)
    coordinator_workers_total.labels(status="busy").set(workers_busy)

    # Generate Prometheus text format
    metrics_output = generate_latest(metrics_registry)

    return PlainTextResponse(
        metrics_output,
        media_type="text/plain; version=0.0.4",
    )
