import json
import logging
import signal
import threading
import time
import urllib.error
import urllib.request

import psutil
from prometheus_client import start_http_server

from core.config import get_settings
from core.redis_client import RedisClient
from processor.ffmpeg_handler import FFmpegHandler
from processor.reporter import ProgressReporter
from processor.tasks import TaskProcessor
from metrics import worker_heartbeat_timestamp, worker_active

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
_jobs_done = 0
_current_status = "idle"
_current_job_id = None


def _http_json(method: str, url: str, body: dict) -> None:
    """Send a small JSON request to the coordinator, log on failure only."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        logger.warning(f"Coordinator call {method} {url} failed: {exc}")


def register_with_coordinator() -> None:
    url = f"{settings.coordinator_url}/workers/register"
    _http_json("POST", url, {"id": settings.worker_id, "status": "idle"})


def send_heartbeat() -> None:
    url = f"{settings.coordinator_url}/workers/{settings.worker_id}/heartbeat"
    body = {
        "status": _current_status,
        "current_job": _current_job_id,
        "cpu_percent": int(psutil.cpu_percent(interval=None)),
        "mem_percent": int(psutil.virtual_memory().percent),
        "jobs_done": _jobs_done,
    }
    _http_json("PUT", url, body)


def heartbeat_loop() -> None:
    while running:
        try:
            send_heartbeat()
        except Exception as exc:
            logger.warning(f"Heartbeat error: {exc}")
        time.sleep(settings.worker_heartbeat_interval)


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
    """Main worker loop - consumes jobs from Redis priority queues."""
    global _jobs_done, _current_status, _current_job_id

    priority_keys = settings.priority_queue_keys
    legacy_key = settings.redis_queue_key

    logger.info(f"Worker {settings.worker_id} started")
    logger.info("Listening to priority queues: %s", priority_keys)

    # Start Prometheus metrics HTTP server
    logger.info(f"Starting metrics server on port {settings.metrics_port}")
    start_http_server(settings.metrics_port)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Register with coordinator and start heartbeat thread
    register_with_coordinator()
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    # BLPOP with multiple keys honors strict priority: Redis returns from the
    # first non-empty key in the list, so we get [high, normal, low] dispatch
    # in a single round trip. ``legacy_key`` is also polled so jobs pushed
    # without a priority suffix (older clients) still get consumed.
    blpop_keys = [*priority_keys, legacy_key]

    while running:
        try:
            # Update heartbeat
            worker_heartbeat_timestamp.set(time.time())

            job_data = redis_client.blpop(blpop_keys, timeout=5)

            if job_data:
                # Mark worker as active
                worker_active.set(1)
                _current_status = "busy"
                try:
                    parsed = json.loads(job_data[1])
                    _current_job_id = parsed.get("id")
                except Exception:
                    _current_job_id = None
                send_heartbeat()

                queue_name, job_json = job_data
                logger.info("Picked job from %s", queue_name)
                success = process_job(job_json)

                if success:
                    logger.info("Job completed successfully")
                else:
                    logger.warning("Job processing failed")

                _jobs_done += 1
                _current_job_id = None
                _current_status = "idle"
                worker_active.set(0)
                send_heartbeat()
            else:
                # Idle - set active to 0
                worker_active.set(0)
                _current_status = "idle"

        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            worker_active.set(0)
            _current_status = "idle"
            time.sleep(1)

    logger.info(f"Worker {settings.worker_id} stopped")
    RedisClient.close()


if __name__ == "__main__":
    main()
