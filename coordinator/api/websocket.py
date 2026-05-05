import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from core.config import get_settings
from core.database import async_session_maker
from core.redis_client import RedisClient
from models.job import Job, JobStatus, Worker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])
settings = get_settings()

HEARTBEAT_INTERVAL_SECONDS = 5
PUBSUB_RECONNECT_DELAY_SECONDS = 3


class ConnectionManager:
    """Tracks active WebSocket clients and fans out messages to all of them."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WS client connected (active=%d)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WS client disconnected (active=%d)", len(self._connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = json.dumps(message, default=str)
        # snapshot to avoid mutation during iteration
        async with self._lock:
            sockets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                # send can fail if the peer is gone before disconnect was handled
                logger.debug("Dropping dead WS client: %s", exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)


manager = ConnectionManager()


def _normalize_worker_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a worker-published event into the dashboard contract.

    The worker publishes events with an ``event`` key and uses ``error_msg``
    rather than ``error`` (see worker/processor/reporter.py). The dashboard
    contract uses ``type`` and ``error``, so we remap here instead of forcing
    a change on the producer side.
    """
    event = raw.get("event")
    if not event:
        return None

    out: Dict[str, Any] = {"type": event}
    for key, value in raw.items():
        if key == "event":
            continue
        if key == "error_msg":
            out["error"] = value
        else:
            out[key] = value
    return out


def _coerce_job_id(raw: Any) -> Optional[UUID]:
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _persist_event_to_db(raw: Dict[str, Any]) -> None:
    """Apply a worker-side event to the corresponding ``jobs`` row.

    The worker only publishes pub/sub messages; without this step the row
    stays at ``queued`` forever and the dashboard's REST refresh overwrites
    the live WebSocket state with stale data, making jobs that actually
    completed look unfinished or failed.
    """
    job_id = _coerce_job_id(raw.get("job_id"))
    if job_id is None:
        return

    event_type = raw.get("event")
    if event_type not in (
        "job_started",
        "job_progress",
        "job_completed",
        "job_failed",
    ):
        return

    try:
        async with async_session_maker() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job is None:
                return

            now = datetime.now(timezone.utc)
            worker_id = raw.get("worker_id")
            if worker_id and not job.worker_id:
                job.worker_id = worker_id
            elif worker_id:
                job.worker_id = worker_id

            if event_type == "job_started":
                job.status = JobStatus.processing
                if job.started_at is None:
                    job.started_at = now
                if job.progress is None:
                    job.progress = 0

            elif event_type == "job_progress":
                # Keep an active job marked as processing even if the start
                # event was lost.
                if job.status not in (JobStatus.completed, JobStatus.failed):
                    job.status = JobStatus.processing
                progress_raw = raw.get("progress")
                try:
                    progress_int = int(progress_raw)
                    job.progress = max(0, min(100, progress_int))
                except (TypeError, ValueError):
                    pass

            elif event_type == "job_completed":
                job.status = JobStatus.completed
                job.progress = 100
                job.completed_at = now
                job.error_msg = None
                output_path = raw.get("output_path")
                if output_path:
                    job.output_path = output_path
                metadata = raw.get("result_metadata")
                if isinstance(metadata, dict):
                    job.result_metadata = metadata

            elif event_type == "job_failed":
                job.status = JobStatus.failed
                job.completed_at = now
                err = raw.get("error_msg") or raw.get("error")
                if err:
                    job.error_msg = str(err)[:1000]

            await session.commit()
    except Exception as exc:
        logger.warning("DB persist for %s/%s failed: %s", event_type, job_id, exc)


async def _pubsub_listener() -> None:
    """Subscribe once to the worker progress channel and fan out to clients."""
    channel_name = settings.redis_progress_channel
    while True:
        pubsub = None
        try:
            redis = RedisClient.get_async_connection()
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel_name)
            logger.info("WS pub/sub subscribed to %s", channel_name)

            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if data is None:
                    continue
                try:
                    parsed = (
                        json.loads(data)
                        if isinstance(data, str)
                        else json.loads(data.decode())
                    )
                except (ValueError, AttributeError) as exc:
                    logger.warning("Invalid pubsub payload dropped: %s", exc)
                    continue

                # Persist first so the next REST hydrate can't undo the WS
                # state, then forward to dashboard clients.
                await _persist_event_to_db(parsed)
                normalized = _normalize_worker_event(parsed)
                if normalized is None:
                    continue
                await manager.broadcast(normalized)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Pub/sub listener error: %s; reconnecting in %ds",
                exc,
                PUBSUB_RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(PUBSUB_RECONNECT_DELAY_SECONDS)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.aclose()
                except Exception:
                    pass


async def _build_queue_snapshot() -> Dict[str, Any]:
    redis_async = RedisClient.get_async_connection()
    queue_by_priority: Dict[str, int] = {"high": 0, "normal": 0, "low": 0}
    for level in queue_by_priority:
        try:
            value = redis_async.llen(f"{settings.redis_queue_key}:{level}")
            if asyncio.iscoroutine(value):
                value = await value
            queue_by_priority[level] = int(value or 0)
        except Exception:
            queue_by_priority[level] = 0
    queue_length = sum(queue_by_priority.values())

    workers_total = 0
    workers_idle = 0
    try:
        async with async_session_maker() as db:
            total_res = await db.execute(select(func.count(Worker.id)))
            workers_total = total_res.scalar() or 0
            idle_res = await db.execute(
                select(func.count(Worker.id)).where(Worker.status == "idle")
            )
            workers_idle = idle_res.scalar() or 0
    except Exception as exc:
        logger.debug("Heartbeat DB query failed: %s", exc)

    workers_busy = max(workers_total - workers_idle, 0)
    return {
        "type": "queue_snapshot",
        "queue_length": int(queue_length or 0),
        "queue_by_priority": queue_by_priority,
        "workers_online": int(workers_total),
        "workers_idle": int(workers_idle),
        "workers_busy": int(workers_busy),
    }


async def _heartbeat_loop() -> None:
    """Emit a global queue snapshot every HEARTBEAT_INTERVAL_SECONDS seconds."""
    while True:
        try:
            snapshot = await _build_queue_snapshot()
            await manager.broadcast(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Heartbeat error: %s", exc)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


_background_tasks: list[asyncio.Task] = []


async def start_background_tasks() -> None:
    """Launch the pub/sub listener and heartbeat loop; called from lifespan startup."""
    if _background_tasks:
        return
    loop = asyncio.get_running_loop()
    _background_tasks.append(
        loop.create_task(_pubsub_listener(), name="ws-pubsub-listener")
    )
    _background_tasks.append(loop.create_task(_heartbeat_loop(), name="ws-heartbeat"))


async def stop_background_tasks() -> None:
    """Cancel background tasks; called from lifespan shutdown."""
    for task in _background_tasks:
        task.cancel()
    for task in _background_tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _background_tasks.clear()
    await RedisClient.aclose()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # we don't consume inbound messages, but we still need to await so the
        # endpoint stays alive and detects disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS endpoint error: %s", exc)
    finally:
        await manager.disconnect(websocket)
