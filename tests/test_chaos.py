"""Tests for the chaos engineering module (scenarios, runner, and REST API)."""

import json
import sys
import uuid
from datetime import datetime, timezone

import fakeredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, "coordinator")

from chaos.runner import ChaosRunner, _KEY_ERROR_RATE, _KEY_SLOW_JOB_DELAY, _QUEUE_KEY
from chaos.scenarios import Scenario, get_available_scenarios, get_scenario_by_id
from core.database import Base, get_db
from core.redis_client import get_redis
from main import app
from models.job import Worker

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def chaos_db_engine():
    """Fresh in-memory SQLite engine for chaos tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def chaos_db_session(chaos_db_engine):
    """Single AsyncSession for direct ORM access in chaos tests."""
    maker = async_sessionmaker(
        chaos_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session


@pytest.fixture
def chaos_redis():
    """Sync FakeRedis instance for chaos tests."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def runner(chaos_db_engine, chaos_redis):
    """ChaosRunner wired to fake DB and Redis; uses a fast clock multiplier."""
    maker = async_sessionmaker(
        chaos_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    return ChaosRunner(redis_client=chaos_redis, db_session_factory=maker)


# ---------------------------------------------------------------------------
# Helper: fake time provider for instant scenario execution
# ---------------------------------------------------------------------------


def _make_instant_runner(chaos_db_engine, chaos_redis) -> ChaosRunner:
    """Return a runner whose internal clock starts at 0 and never advances."""
    maker = async_sessionmaker(
        chaos_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    counter = [0.0]

    def _fixed_time() -> float:
        return counter[0]

    return ChaosRunner(
        redis_client=chaos_redis,
        db_session_factory=maker,
        time_provider=_fixed_time,
    )


# ---------------------------------------------------------------------------
# HTTP client fixture wired to chaos app with overrides
# ---------------------------------------------------------------------------


@pytest.fixture
async def chaos_client(chaos_db_engine, chaos_redis, runner):
    """AsyncClient with DB + Redis + ChaosRunner overrides active."""
    import httpx
    import api.routes.chaos as chaos_module

    maker = async_sessionmaker(
        chaos_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with maker() as session:
            yield session

    def override_get_redis():
        return chaos_redis

    def override_get_chaos_runner():
        return runner

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis
    # Use the module's get_chaos_runner as the stable dependency key.
    app.dependency_overrides[chaos_module.get_chaos_runner] = override_get_chaos_runner

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. GET /chaos/scenarios — returns all 4 presets
# ---------------------------------------------------------------------------


async def test_list_scenarios_returns_four(chaos_client):
    """GET /chaos/scenarios returns exactly 4 preset scenarios."""
    r = await chaos_client.get("/chaos/scenarios")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 4
    ids = {s["id"] for s in data}
    assert ids == {
        "worker_overload",
        "redis_outage",
        "cascading_failures",
        "slow_network",
    }


async def test_list_scenarios_schema(chaos_client):
    """Each scenario has required fields with correct types."""
    r = await chaos_client.get("/chaos/scenarios")
    assert r.status_code == 200
    for s in r.json():
        assert "id" in s
        assert "name" in s
        assert "description" in s
        assert isinstance(s["duration_seconds"], int)
        assert isinstance(s["actions"], list)
        assert len(s["actions"]) > 0


# ---------------------------------------------------------------------------
# 2. POST /chaos/runs — valid scenario_id returns run_id
# ---------------------------------------------------------------------------


async def test_start_run_returns_run_id(chaos_client):
    """POST /chaos/runs with valid scenario_id returns 200 and run_id."""
    r = await chaos_client.post("/chaos/runs", json={"scenario_id": "slow_network"})
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data
    assert len(data["run_id"]) > 0


# ---------------------------------------------------------------------------
# 3. POST /chaos/runs — unknown scenario_id returns 404
# ---------------------------------------------------------------------------


async def test_start_run_unknown_scenario_returns_404(chaos_client):
    """POST /chaos/runs with unknown scenario_id returns 404."""
    r = await chaos_client.post("/chaos/runs", json={"scenario_id": "does_not_exist"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4. Starting a second scenario while one is active returns 409
# ---------------------------------------------------------------------------


async def test_start_run_while_active_returns_409(chaos_client):
    """POST /chaos/runs returns 409 when another scenario is running."""
    # Start first run — slow_network has no wall-clock waits at t=0 actions.
    r1 = await chaos_client.post("/chaos/runs", json={"scenario_id": "slow_network"})
    assert r1.status_code == 200

    # Attempt to start a second scenario immediately.
    r2 = await chaos_client.post("/chaos/runs", json={"scenario_id": "redis_outage"})
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 5. GET /chaos/runs/{run_id} — status endpoint
# ---------------------------------------------------------------------------


async def test_get_run_status(chaos_client):
    """GET /chaos/runs/{run_id} returns status dict with expected fields."""
    r = await chaos_client.post("/chaos/runs", json={"scenario_id": "slow_network"})
    run_id = r.json()["run_id"]

    r2 = await chaos_client.get(f"/chaos/runs/{run_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["run_id"] == run_id
    assert data["scenario_id"] == "slow_network"
    assert data["state"] in ("running", "completed", "cancelled", "failed")
    assert "started_at" in data
    assert "actions_executed" in data


async def test_get_run_unknown_returns_404(chaos_client):
    """GET /chaos/runs/{run_id} for unknown run_id returns 404."""
    r = await chaos_client.get(f"/chaos/runs/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. DELETE /chaos/runs/{run_id} — stops scenario, state becomes cancelled
# ---------------------------------------------------------------------------


async def test_stop_run_sets_cancelled(chaos_client):
    """DELETE /chaos/runs/{run_id} cancels the run; state is 'cancelled'."""
    r = await chaos_client.post("/chaos/runs", json={"scenario_id": "slow_network"})
    run_id = r.json()["run_id"]

    r2 = await chaos_client.delete(f"/chaos/runs/{run_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["state"] == "cancelled"


async def test_stop_run_unknown_returns_404(chaos_client):
    """DELETE /chaos/runs/{run_id} for unknown run_id returns 404."""
    r = await chaos_client.delete(f"/chaos/runs/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. spike_queue actually pushes jobs to Redis queue
# ---------------------------------------------------------------------------


async def test_spike_queue_pushes_jobs(chaos_db_engine, chaos_redis):
    """spike_queue action pushes the correct number of jobs to Redis."""
    runner = _make_instant_runner(chaos_db_engine, chaos_redis)

    before = chaos_redis.llen(_QUEUE_KEY)

    # Trigger the spike_queue handler directly.
    await runner._handle_spike_queue({"num_jobs": 5, "job_type": "thumbnail"})

    after = chaos_redis.llen(_QUEUE_KEY)
    assert after - before == 5

    # Validate payload shape.
    items = chaos_redis.lrange(_QUEUE_KEY, 0, -1)
    for item in items[-5:]:
        payload = json.loads(item)
        assert payload["type"] == "thumbnail"
        assert payload["id"].startswith("chaos-")
        assert "input_path" in payload


# ---------------------------------------------------------------------------
# 8. inject_errors sets / clears the chaos:error_rate key
# ---------------------------------------------------------------------------


async def test_inject_errors_sets_redis_key(chaos_db_engine, chaos_redis):
    """inject_errors action writes chaos:error_rate to Redis."""
    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_inject_errors({"error_rate": 0.7})
    assert chaos_redis.get(_KEY_ERROR_RATE) == "0.7"


async def test_inject_errors_clears_redis_key(chaos_db_engine, chaos_redis):
    """inject_errors with rate=0 removes the Redis key."""
    chaos_redis.set(_KEY_ERROR_RATE, "0.5")
    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_inject_errors({"error_rate": 0.0})
    assert chaos_redis.get(_KEY_ERROR_RATE) is None


# ---------------------------------------------------------------------------
# 9. slow_job sets / clears the chaos:slow_job_delay_ms key
# ---------------------------------------------------------------------------


async def test_slow_job_sets_redis_key(chaos_db_engine, chaos_redis):
    """slow_job action writes chaos:slow_job_delay_ms to Redis."""
    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_slow_job({"delay_ms": 2000})
    assert chaos_redis.get(_KEY_SLOW_JOB_DELAY) == "2000"


async def test_slow_job_clears_redis_key(chaos_db_engine, chaos_redis):
    """slow_job with delay_ms=0 removes the Redis key."""
    chaos_redis.set(_KEY_SLOW_JOB_DELAY, "2000")
    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_slow_job({"delay_ms": 0})
    assert chaos_redis.get(_KEY_SLOW_JOB_DELAY) is None


# ---------------------------------------------------------------------------
# 10. kill_worker flips DB status; cleanup restores it
# ---------------------------------------------------------------------------


async def test_kill_worker_sets_offline(chaos_db_engine, chaos_db_session, chaos_redis):
    """kill_worker sets the worker status to 'offline' in the DB."""
    w = Worker(
        id="test-worker-1",
        status="idle",
        jobs_done=0,
        last_seen=datetime.now(timezone.utc),
    )
    chaos_db_session.add(w)
    await chaos_db_session.commit()

    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_kill_worker({"worker_id": "test-worker-1"})

    await chaos_db_session.refresh(w)
    assert w.status == "offline"


async def test_cleanup_restores_killed_workers(
    chaos_db_engine, chaos_db_session, chaos_redis
):
    """_cleanup restores workers that were killed during the scenario."""
    w = Worker(
        id="test-worker-2",
        status="idle",
        jobs_done=0,
        last_seen=datetime.now(timezone.utc),
    )
    chaos_db_session.add(w)
    await chaos_db_session.commit()

    runner = _make_instant_runner(chaos_db_engine, chaos_redis)
    await runner._handle_kill_worker({"worker_id": "test-worker-2"})
    await runner._cleanup()

    await chaos_db_session.refresh(w)
    assert w.status == "idle"


# ---------------------------------------------------------------------------
# 11. GET /chaos/runs lists all runs
# ---------------------------------------------------------------------------


async def test_list_runs_includes_started_run(chaos_client):
    """GET /chaos/runs includes the run that was just started."""
    r = await chaos_client.post("/chaos/runs", json={"scenario_id": "slow_network"})
    run_id = r.json()["run_id"]

    r2 = await chaos_client.get("/chaos/runs")
    assert r2.status_code == 200
    runs = r2.json()
    assert any(run["run_id"] == run_id for run in runs)


# ---------------------------------------------------------------------------
# 12. Unit-level: get_available_scenarios returns 4 items
# ---------------------------------------------------------------------------


def test_get_available_scenarios_count():
    """get_available_scenarios() returns exactly 4 presets."""
    scenarios = get_available_scenarios()
    assert len(scenarios) == 4
    assert all(isinstance(s, Scenario) for s in scenarios)


def test_get_scenario_by_id_found():
    """get_scenario_by_id returns the right scenario for a known id."""
    s = get_scenario_by_id("worker_overload")
    assert s is not None
    assert s.id == "worker_overload"
    assert len(s.actions) >= 2


def test_get_scenario_by_id_not_found():
    """get_scenario_by_id returns None for an unknown id."""
    assert get_scenario_by_id("nonexistent") is None
