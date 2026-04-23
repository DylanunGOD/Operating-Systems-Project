from sqlalchemy import Column, String, Integer, Text, JSON, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum
from core.database import Base


class JobType(str, enum.Enum):
    """Job types supported by the system"""

    convert_video = "convert_video"
    extract_audio = "extract_audio"
    thumbnail = "thumbnail"


class JobStatus(str, enum.Enum):
    """Job status states"""

    pending = "pending"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Job(Base):
    """Job model for multimedia processing tasks"""

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(Enum(JobType, name="job_type", create_type=False), nullable=False)
    status = Column(
        Enum(JobStatus, name="job_status", create_type=False),
        nullable=False,
        default=JobStatus.pending,
    )
    input_path = Column(String, nullable=False)
    output_path = Column(String)
    params = Column(JSON, default={})
    worker_id = Column(String)
    progress = Column(Integer, default=0)
    error_msg = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    retry_count = Column(Integer, default=0)

    def __repr__(self):
        return (
            f"<Job(id={self.id}, type={self.type}, status={self.status}, "
            f"worker={self.worker_id}, progress={self.progress}%)>"
        )


class Worker(Base):
    """Worker model for tracking worker status"""

    __tablename__ = "workers"

    id = Column(String, primary_key=True)
    status = Column(String, default="idle")
    current_job = Column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    cpu_percent = Column(Integer)
    mem_percent = Column(Integer)
    jobs_done = Column(Integer, default=0)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return (
            f"<Worker(id={self.id}, status={self.status}, "
            f"cpu={self.cpu_percent}%, mem={self.mem_percent}%)>"
        )


class Event(Base):
    """Event log for audit trail and monitoring"""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    worker_id = Column(String)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Event(id={self.id}, job={self.job_id}, " f"type={self.event_type})>"
