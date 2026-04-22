import json
import logging
import signal
import time

from core.config import get_settings
from core.redis_client import RedisClient
from processor.ffmpeg_handler import FFmpegHandler
from processor.reporter import ProgressReporter
from processor.tasks import TaskProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
redis_client = RedisClient.get_connection()
task_processor = TaskProcessor(
    ffmpeg=FFmpegHandler(),
    reporter=ProgressReporter(
        redis_client=redis_client,
        progress_channel=settings.redis_progress_channel,
    ),
)

running = True


def signal_handler(sig, frame):
    """Handle graceful shutdown"""
    global running
    logger.info(f"Worker {settings.worker_id} shutting down...")
    running = False


def process_job(job_data: str) -> bool:
    """Process a single job from the queue"""
    try:
        job = json.loads(job_data)

        job_id = job.get("id")
        job_type = job.get("type")
        input_path = job.get("input_path")
        output_path = job.get("output_path")
        params = job.get("params", {})

        logger.info(
            f"Processing job {job_id} ({job_type}) on worker {settings.worker_id}"
        )

        success = task_processor.execute(
            job_id=job_id,
            job_type=job_type,
            worker_id=settings.worker_id,
            input_path=input_path,
            output_path=output_path,
            params=params,
        )

        return success

    except json.JSONDecodeError as e:
        logger.error(f"Invalid job JSON: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error processing job: {e}")
        return False


def main():
    """Main worker loop - consumes jobs from Redis queue"""
    logger.info(f"Worker {settings.worker_id} started")
    logger.info(f"Listening to queue: {settings.redis_queue_key}")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    while running:
        try:
            job_data = redis_client.blpop(
                settings.redis_queue_key,
                timeout=5,
            )

            if job_data:
                queue_name, job_json = job_data
                success = process_job(job_json)

                if success:
                    logger.info("Job completed successfully")
                else:
                    logger.warning("Job processing failed")

        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            time.sleep(1)

    logger.info(f"Worker {settings.worker_id} stopped")
    RedisClient.close()


if __name__ == "__main__":
    main()
