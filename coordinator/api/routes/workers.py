from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.sql import func

from core.database import get_db
from models.job import Worker
from models.schemas import (
    WorkerListResponse,
    WorkerResponse,
    WorkerRegisterRequest,
    WorkerHeartbeatRequest,
)

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("", response_model=WorkerListResponse)
async def list_workers(db: AsyncSession = Depends(get_db)):
    """Get all workers and their status"""
    result = await db.execute(select(Worker))
    workers = result.scalars().all()

    return WorkerListResponse(workers=workers)


@router.post("/register", response_model=WorkerResponse)
async def register_worker(
    payload: WorkerRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a worker (upsert by id)."""
    result = await db.execute(select(Worker).where(Worker.id == payload.id))
    worker = result.scalar_one_or_none()

    if worker is None:
        worker = Worker(id=payload.id, status=payload.status)
        db.add(worker)
    else:
        worker.status = payload.status
        worker.last_seen = func.now()

    await db.commit()
    await db.refresh(worker)
    return worker


@router.put("/{worker_id}/heartbeat", response_model=WorkerResponse)
async def heartbeat_worker(
    worker_id: str,
    payload: WorkerHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update a worker's heartbeat / live stats."""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()

    if worker is None:
        worker = Worker(id=worker_id, status=payload.status or "idle")
        db.add(worker)
    else:
        if payload.status is not None:
            worker.status = payload.status
        if payload.cpu_percent is not None:
            worker.cpu_percent = payload.cpu_percent
        if payload.mem_percent is not None:
            worker.mem_percent = payload.mem_percent
        if payload.jobs_done is not None:
            worker.jobs_done = payload.jobs_done
        worker.current_job = payload.current_job
        worker.last_seen = func.now()

    await db.commit()
    await db.refresh(worker)
    return worker


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    """Get status of a specific worker"""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    return worker
