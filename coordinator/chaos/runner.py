"""ChaosRunner — executes scenario actions on a timed schedule."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import update

from chaos.scenarios import ScenarioAction, get_scenario_by_id

logger = logging.getLogger(__name__)

# Redis keys written by the runner so workers can read them.
_KEY_SLOW_JOB_DELAY = "chaos:slow_job_delay_ms"
_KEY_ERROR_RATE = "chaos:error_rate"
_QUEUE_KEY = "jobs:queue"


class _RunRecord:
    """Internal state for a single scenario execution."""

    def __init__(self, run_id: str, scenario_id: str) -> None:
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.state: str = "running"
        self.started_at: datetime = datetime.now(timezone.utc)
        self.actions_executed: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "state": self.state,
            "started_at": self.started_at.isoformat(),
            "actions_executed": self.actions_executed,
        }


class ChaosRunner:
    """Orchestrates chaos scenario execution.

    Parameters
    ----------
    redis_client:
        A *synchronous* ``redis.Redis`` instance (the coordinator's existing
        client).  Action handlers call sync Redis methods to stay compatible
        with the FakeRedis test fixture.
    db_session_factory:
        A zero-argument callable that returns an ``AsyncSession`` context
        manager (i.e. ``async_sessionmaker`` instance).
    time_provider:
        Optional callable returning the current monotonic time as a float.
        Injected in tests to fast-forward the clock without real sleeps.
    """

    def __init__(
        self,
        redis_client: Any,
        db_session_factory: Any,
        *,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._redis = redis_client
        self._db_factory = db_session_factory
        self._time = time_provider or (lambda: asyncio.get_event_loop().time())
        self._runs: dict[str, _RunRecord] = {}
        # worker-ids that were flipped to "offline" by an active scenario so
        # we can restore them on cleanup.
        self._killed_workers: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, scenario_id: str, *, speed_multiplier: float = 1.0) -> str:
        """Begin running *scenario_id*; return the new run_id.

        Raises
        ------
        ValueError
            If *scenario_id* does not exist, or if another scenario is already
            running.
        """
        scenario = get_scenario_by_id(scenario_id)
        if scenario is None:
            raise ValueError(f"unknown scenario: {scenario_id!r}")

        # Only one active run at a time.
        if self._active_run() is not None:
            raise ValueError("another scenario is already running")

        run_id = str(uuid.uuid4())
        record = _RunRecord(run_id, scenario_id)
        self._runs[run_id] = record

        task = asyncio.get_event_loop().create_task(
            self._execute(record, scenario, speed_multiplier),
            name=f"chaos-{run_id}",
        )
        record._task = task
        logger.info("Chaos run %s started (scenario=%s)", run_id, scenario_id)
        return run_id

    async def stop(self, run_id: str) -> bool:
        """Cancel a running scenario.  Returns True if it was running."""
        record = self._runs.get(run_id)
        if record is None:
            return False
        if record.state != "running":
            return False

        if record._task and not record._task.done():
            record._task.cancel()
            try:
                await record._task
            except (asyncio.CancelledError, Exception):
                pass

        record.state = "cancelled"
        await self._cleanup()
        logger.info("Chaos run %s cancelled", run_id)
        return True

    def status(self, run_id: str) -> dict[str, Any] | None:
        """Return status dict for *run_id*, or None if unknown."""
        record = self._runs.get(run_id)
        if record is None:
            return None
        return record.to_dict()

    def list_runs(self) -> list[dict[str, Any]]:
        """Return status dicts for all runs (active + historical)."""
        return [r.to_dict() for r in self._runs.values()]

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _active_run(self) -> _RunRecord | None:
        """Return the currently running record, or None."""
        for r in self._runs.values():
            if r.state == "running":
                return r
        return None

    async def _execute(
        self, record: _RunRecord, scenario: Any, speed_multiplier: float
    ) -> None:
        """Run scenario actions at their scheduled offsets, then clean up."""
        try:
            # Group actions by their at_second offset.
            schedule: dict[int, list[ScenarioAction]] = {}
            for action in scenario.actions:
                schedule.setdefault(action.at_second, []).append(action)

            start_mono = self._time()
            sorted_offsets = sorted(schedule.keys())

            for offset in sorted_offsets:
                # How long to sleep before this batch of actions.
                target_mono = start_mono + offset / speed_multiplier
                now = self._time()
                delay = target_mono - now
                if delay > 0:
                    await asyncio.sleep(delay)

                for action in schedule[offset]:
                    await self._dispatch(record, action)

            # Wait out any remaining duration.
            elapsed = (self._time() - start_mono) * speed_multiplier
            remaining = scenario.duration_seconds - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining / speed_multiplier)

            record.state = "completed"
            logger.info("Chaos run %s completed", record.run_id)
        except asyncio.CancelledError:
            record.state = "cancelled"
            raise
        except Exception as exc:
            record.state = "failed"
            logger.error("Chaos run %s failed: %s", record.run_id, exc)
        finally:
            await self._cleanup()

    async def _dispatch(self, record: _RunRecord, action: ScenarioAction) -> None:
        """Route a single action to its handler."""
        logger.debug(
            "Run %s dispatching action %s at_second=%d",
            record.run_id,
            action.type,
            action.at_second,
        )
        try:
            if action.type == "kill_worker":
                await self._handle_kill_worker(action.params)
            elif action.type == "spike_queue":
                await self._handle_spike_queue(action.params)
            elif action.type == "redis_disconnect":
                await self._handle_redis_disconnect(action.params)
            elif action.type == "slow_job":
                await self._handle_slow_job(action.params)
            elif action.type == "inject_errors":
                await self._handle_inject_errors(action.params)
            else:
                logger.warning("Unknown action type: %s", action.type)
                return

            record.actions_executed.append(
                {
                    "type": action.type,
                    "params": action.params,
                    "at_second": action.at_second,
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            logger.error("Action %s failed: %s", action.type, exc)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _handle_kill_worker(self, params: dict[str, Any]) -> None:
        """Set a worker's status to 'offline' in the database."""
        worker_id = params.get("worker_id")
        if not worker_id:
            logger.warning("kill_worker: missing worker_id param")
            return

        from models.job import Worker  # local import to avoid circular imports

        async with self._db_factory() as session:  # type: AsyncSession
            await session.execute(
                update(Worker).where(Worker.id == worker_id).values(status="offline")
            )
            await session.commit()
        self._killed_workers.add(worker_id)
        logger.info("kill_worker: set worker %s to offline", worker_id)

    async def _handle_spike_queue(self, params: dict[str, Any]) -> None:
        """Push N fake jobs onto the Redis jobs queue."""
        num_jobs: int = int(params.get("num_jobs", 10))
        job_type: str = params.get("job_type", "thumbnail")

        jobs_json = []
        for _ in range(num_jobs):
            job_id = f"chaos-{uuid.uuid4()}"
            payload = json.dumps(
                {
                    "id": job_id,
                    "type": job_type,
                    "input_path": f"/chaos/fake/{job_id}.mp4",
                    "output_path": None,
                    "params": {"chaos": True},
                }
            )
            jobs_json.append(payload)

        if jobs_json:
            self._redis.lpush(_QUEUE_KEY, *jobs_json)
        logger.info("spike_queue: pushed %d fake jobs", num_jobs)

    async def _handle_redis_disconnect(self, params: dict[str, Any]) -> None:
        """Simulate Redis disconnect by flushing the queue (non-destructive log).

        We do NOT actually close the Redis connection — that would break other
        parts of the app and the test suite.  Instead, when action=disconnect
        we record the current queue length and clear it; on reconnect we log
        the restore.  Workers and the queue monitor will see an empty queue
        during the "outage" window.
        """
        action = params.get("action", "disconnect")
        if action == "disconnect":
            length = self._redis.llen(_QUEUE_KEY)
            self._redis.delete(_QUEUE_KEY)
            logger.info(
                "redis_disconnect: simulated outage; cleared %d queue items", length
            )
        else:
            logger.info("redis_disconnect: simulated reconnect")

    async def _handle_slow_job(self, params: dict[str, Any]) -> None:
        """Write/clear a Redis key that workers read to add artificial delay."""
        delay_ms = int(params.get("delay_ms", 0))
        if delay_ms > 0:
            self._redis.set(_KEY_SLOW_JOB_DELAY, str(delay_ms))
            logger.info("slow_job: set delay to %d ms", delay_ms)
        else:
            self._redis.delete(_KEY_SLOW_JOB_DELAY)
            logger.info("slow_job: cleared delay")

    async def _handle_inject_errors(self, params: dict[str, Any]) -> None:
        """Write/clear a Redis key that workers read to inject random errors."""
        error_rate = float(params.get("error_rate", 0.0))
        if error_rate > 0.0:
            self._redis.set(_KEY_ERROR_RATE, str(error_rate))
            logger.info("inject_errors: set error rate to %.2f", error_rate)
        else:
            self._redis.delete(_KEY_ERROR_RATE)
            logger.info("inject_errors: cleared error rate")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Remove chaos keys from Redis and restore flipped worker statuses."""
        try:
            self._redis.delete(_KEY_SLOW_JOB_DELAY)
            self._redis.delete(_KEY_ERROR_RATE)
        except Exception as exc:
            logger.error("cleanup: failed to clear Redis keys: %s", exc)

        if self._killed_workers:
            from models.job import Worker  # local import

            workers_to_restore = set(self._killed_workers)
            self._killed_workers.clear()
            try:
                async with self._db_factory() as session:
                    await session.execute(
                        update(Worker)
                        .where(Worker.id.in_(workers_to_restore))
                        .values(status="idle")
                    )
                    await session.commit()
                logger.info("cleanup: restored workers %s to idle", workers_to_restore)
            except Exception as exc:
                logger.error("cleanup: failed to restore workers: %s", exc)
