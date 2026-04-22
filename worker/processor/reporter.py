import json
import logging
from datetime import datetime
from redis import Redis

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Reports job progress to Redis pub/sub"""

    def __init__(self, redis_client: Redis, progress_channel: str):
        self.redis = redis_client
        self.progress_channel = progress_channel

    def report_progress(
        self,
        job_id: str,
        worker_id: str,
        progress: int,
    ) -> None:
        """Publish progress update to Redis"""
        message = {
            "event": "job_progress",
            "job_id": job_id,
            "worker_id": worker_id,
            "progress": progress,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self.redis.publish(
                self.progress_channel,
                json.dumps(message),
            )
            logger.debug(f"Progress reported: {job_id} = {progress}%")
        except Exception as e:
            logger.error(f"Failed to report progress: {e}")

    def report_started(
        self,
        job_id: str,
        worker_id: str,
    ) -> None:
        """Report that job processing started"""
        message = {
            "event": "job_started",
            "job_id": job_id,
            "worker_id": worker_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self.redis.publish(
                self.progress_channel,
                json.dumps(message),
            )
            logger.info(f"Job started: {job_id}")
        except Exception as e:
            logger.error(f"Failed to report job start: {e}")

    def report_completed(
        self,
        job_id: str,
        worker_id: str,
        output_path: str,
    ) -> None:
        """Report that job processing completed successfully"""
        message = {
            "event": "job_completed",
            "job_id": job_id,
            "worker_id": worker_id,
            "output_path": output_path,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self.redis.publish(
                self.progress_channel,
                json.dumps(message),
            )
            logger.info(f"Job completed: {job_id}")
        except Exception as e:
            logger.error(f"Failed to report job completion: {e}")

    def report_failed(
        self,
        job_id: str,
        worker_id: str,
        error_msg: str,
    ) -> None:
        """Report that job processing failed"""
        message = {
            "event": "job_failed",
            "job_id": job_id,
            "worker_id": worker_id,
            "error_msg": error_msg,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            self.redis.publish(
                self.progress_channel,
                json.dumps(message),
            )
            logger.error(f"Job failed: {job_id} - {error_msg}")
        except Exception as e:
            logger.error(f"Failed to report job failure: {e}")
