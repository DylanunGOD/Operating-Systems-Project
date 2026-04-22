import json
import logging
from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from models.job import Job, JobStatus

logger = logging.getLogger(__name__)


class JobScheduler:
    """Schedules jobs to the distributed queue"""

    def __init__(self, redis_client: Redis, queue_key: str):
        self.redis = redis_client
        self.queue_key = queue_key

    async def enqueue_job(self, db: AsyncSession, job: Job) -> bool:
        """
        Enqueue a job to Redis queue and update status to 'queued'
        """
        try:
            job_data = {
                "id": str(job.id),
                "type": job.type,
                "input_path": job.input_path,
                "output_path": job.output_path,
                "params": job.params,
            }

            job_json = json.dumps(job_data)
            self.redis.rpush(self.queue_key, job_json)

            job.status = JobStatus.queued
            await db.commit()

            logger.info(f"Job {job.id} enqueued to {self.queue_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")
            await db.rollback()
            return False

    def get_queue_length(self) -> int:
        """Get current queue length"""
        try:
            length = self.redis.llen(self.queue_key)
            return length
        except Exception as e:
            logger.error(f"Failed to get queue length: {e}")
            return 0

    def clear_queue(self) -> bool:
        """Clear all jobs from queue (for testing only)"""
        try:
            self.redis.delete(self.queue_key)
            logger.warning("Queue cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear queue: {e}")
            return False
