from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from models.job import Worker
from models.schemas import WorkerListResponse, WorkerResponse

router = APIRouter(prefix="/workers", tags=["workers"])


@router.get("", response_model=WorkerListResponse)
async def list_workers(db: AsyncSession = Depends(get_db)):
    """Get all workers and their status"""
    result = await db.execute(select(Worker))
    workers = result.scalars().all()

    return WorkerListResponse(workers=workers)


@router.get("/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    """Get status of a specific worker"""
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    worker = result.scalar_one_or_none()

    if not worker:
        return {"error": f"Worker {worker_id} not found"}

    return worker
