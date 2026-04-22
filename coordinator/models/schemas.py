from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


class JobType(str, Enum):
    """Job types"""

    convert_video = "convert_video"
    extract_audio = "extract_audio"
    thumbnail = "thumbnail"


class JobStatus(str, Enum):
    """Job status"""

    pending = "pending"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobCreate(BaseModel):
    """Request schema for creating a new job"""

    type: JobType
    input_path: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)


class JobUpdate(BaseModel):
    """Request schema for updating a job"""

    status: Optional[JobStatus] = None
    progress: Optional[int] = None
    worker_id: Optional[str] = None
    error_msg: Optional[str] = None


class JobResponse(BaseModel):
    """Response schema for job details"""

    id: UUID
    type: JobType
    status: JobStatus
    input_path: str
    output_path: Optional[str] = None
    params: Dict[str, Any]
    worker_id: Optional[str] = None
    progress: int
    error_msg: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """Response schema for job list"""

    total: int
    jobs: list[JobResponse]


class WorkerResponse(BaseModel):
    """Response schema for worker status"""

    id: str
    status: str
    current_job: Optional[UUID] = None
    cpu_percent: Optional[float] = None
    mem_percent: Optional[float] = None
    jobs_done: int
    last_seen: datetime

    class Config:
        from_attributes = True


class WorkerListResponse(BaseModel):
    """Response schema for worker list"""

    workers: list[WorkerResponse]


class MetricsResponse(BaseModel):
    """Response schema for system metrics"""

    queue_length: int
    jobs_total: int
    jobs_completed: int
    jobs_failed: int
    jobs_processing: int
    workers_online: int
    workers_idle: int
    workers_busy: int
    average_processing_time_seconds: Optional[float] = None


class EventResponse(BaseModel):
    """Response schema for event details"""

    id: int
    job_id: Optional[UUID] = None
    worker_id: Optional[str] = None
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
