import json
import logging
from typing import Optional

from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from models.job import Job, JobStatus

logger = logging.getLogger(__name__)


VALID_PRIORITIES = ("high", "normal", "low")


class JobScheduler:
    """Schedules jobs to the distributed queue with priority routing."""

    def __init__(self, redis_client: Redis, queue_key: str):
        self.redis = redis_client
        self.queue_key = queue_key

    def _key_for_priority(self, priority: Optional[str]) -> str:
        if priority not in VALID_PRIORITIES:
            priority = "normal"
        return f"{self.queue_key}:{priority}"

    async def enqueue_job(self, db: AsyncSession, job: Job) -> bool:
        """Push the job onto the priority list matching ``job.priority`` and
        flip its row status to ``queued``."""
        try:
            priority = getattr(job, "priority", None) or "normal"
            target_key = self._key_for_priority(priority)

            job_data = {
                "id": str(job.id),
                "type": job.type.value if hasattr(job.type, "value") else str(job.type),
                "input_path": job.input_path,
                "output_path": job.output_path,
                "priority": priority,
                "params": job.params,
            }

            self.redis.rpush(target_key, json.dumps(job_data))

            job.status = JobStatus.queued
            await db.commit()

            logger.info("Job %s enqueued to %s", job.id, target_key)
            return True

        except Exception as exc:
            logger.error("Failed to enqueue job: %s", exc)
            await db.rollback()
            return False

    def get_queue_length(self) -> int:
        """Sum of lengths across all three priority lists."""
        try:
            total = 0
            for level in VALID_PRIORITIES:
                total += int(self.redis.llen(f"{self.queue_key}:{level}") or 0)
            return total
        except Exception as exc:
            logger.error("Failed to get queue length: %s", exc)
            return 0

    def get_queue_lengths_by_priority(self) -> dict[str, int]:
        """Per-priority depth — used by metrics and the dashboard."""
        result: dict[str, int] = {}
        for level in VALID_PRIORITIES:
            try:
                result[level] = int(self.redis.llen(f"{self.queue_key}:{level}") or 0)
            except Exception:
                result[level] = 0
        return result

    def clear_queue(self) -> bool:
        """Drop all priority lists. Test-only."""
        try:
            for level in VALID_PRIORITIES:
                self.redis.delete(f"{self.queue_key}:{level}")
            logger.warning("Queue cleared")
            return True
        except Exception as exc:
            logger.error("Failed to clear queue: %s", exc)
            return False
