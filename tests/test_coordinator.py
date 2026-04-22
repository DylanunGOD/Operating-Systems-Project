"""Unit tests for the coordinator service."""

import json
import sys
import uuid

import fakeredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, "coordinator")

from core.scheduler import JobScheduler
from models.job import Job, JobStatus, JobType, Worker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

JOB_PAYLOAD = {
    "type": "thumbnail",
    "input_path": "/data/video.mp4",
    "params": {"width": 320},
}


# ---------------------------------------------------------------------------
# 1. POST /jobs
# ---------------------------------------------------------------------------


async def test_create_job_returns_201_like_response(async_client):
    """POST /jobs with valid body returns the created job."""
    r = await async_client.post("/jobs", json=JOB_PAYLOAD)
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "thumbnail"
    assert data["input_path"] == "/data/video.mp4"
    assert "id" in data


async def test_create_job_status_is_queued(async_client):
    """POST /jobs sets status to 'queued' after successful enqueue."""
    r = await async_client.post("/jobs", json=JOB_PAYLOAD)
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


async def test_create_job_enqueues_to_redis(async_client, redis_mock):
    """POST /jobs pushes one item to the Redis queue."""
    queue_key = "jobs:queue"
    before = redis_mock.llen(queue_key)
    await async_client.post("/jobs", json=JOB_PAYLOAD)
    assert redis_mock.llen(queue_key) == before + 1


async def test_create_job_redis_payload_shape(async_client, redis_mock):
    """Item pushed to Redis contains required keys with correct values."""
    await async_client.post("/jobs", json=JOB_PAYLOAD)
    raw = redis_mock.lrange("jobs:queue", -1, -1)[0]
    payload = json.loads(raw)
    assert payload["type"] == "thumbnail"
    assert payload["input_path"] == "/data/video.mp4"
    assert "id" in payload


async def test_create_job_db_record_created(async_client, db_session):
    """POST /jobs persists a row to the jobs table."""
    from sqlalchemy import select

    r = await async_client.post("/jobs", json=JOB_PAYLOAD)
    job_id = r.json()["id"]
    result = await db_session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
    job = result.scalar_one_or_none()
    assert job is not None
    assert str(job.id) == job_id


# ---------------------------------------------------------------------------
# 2. GET /jobs (list)
# ---------------------------------------------------------------------------


async def test_list_jobs_empty(async_client):
    """GET /jobs returns empty list when no jobs exist."""
    r = await async_client.get("/jobs")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["jobs"] == []


async def test_list_jobs_returns_created_jobs(async_client, sample_job_factory):
    """GET /jobs includes jobs previously created."""
    await sample_job_factory()
    await sample_job_factory()
    r = await async_client.get("/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 2


async def test_list_jobs_filter_by_status(async_client, sample_job_factory):
    """GET /jobs?status=pending returns only pending jobs."""
    await sample_job_factory(status="pending")
    await sample_job_factory(status="completed")
    r = await async_client.get("/jobs?status=pending")
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"


async def test_list_jobs_filter_by_worker_id(async_client, sample_job_factory):
    """GET /jobs?worker_id=w1 returns only jobs assigned to that worker."""
    await sample_job_factory(worker_id="w1")
    await sample_job_factory(worker_id="w2")
    r = await async_client.get("/jobs?worker_id=w1")
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["worker_id"] == "w1"


async def test_list_jobs_filter_no_match(async_client, sample_job_factory):
    """GET /jobs?status=failed returns empty list when none match."""
    await sample_job_factory(status="pending")
    r = await async_client.get("/jobs?status=failed")
    assert r.status_code == 200
    assert r.json()["jobs"] == []


# ---------------------------------------------------------------------------
# 3. GET /jobs/{id}
# ---------------------------------------------------------------------------


async def test_get_job_existing(async_client, sample_job_factory):
    """GET /jobs/{id} returns 200 and correct job data for an existing job."""
    job = await sample_job_factory(job_type="extract_audio")
    r = await async_client.get(f"/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["id"] == str(job.id)
    assert r.json()["type"] == "extract_audio"


async def test_get_job_missing(async_client):
    """GET /jobs/{id} returns 404 for a non-existent UUID."""
    r = await async_client.get(f"/jobs/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_get_job_invalid_uuid(async_client):
    """GET /jobs/not-a-uuid returns 422 unprocessable entity."""
    r = await async_client.get("/jobs/not-a-uuid")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. PATCH /jobs/{id}
# ---------------------------------------------------------------------------


async def test_patch_job_updates_status(async_client, sample_job_factory):
    """PATCH /jobs/{id} can update the job status."""
    job = await sample_job_factory(status="pending")
    r = await async_client.patch(f"/jobs/{job.id}", json={"status": "processing"})
    assert r.status_code == 200
    assert r.json()["status"] == "processing"


async def test_patch_job_updates_progress(async_client, sample_job_factory):
    """PATCH /jobs/{id} can update the progress field."""
    job = await sample_job_factory()
    r = await async_client.patch(f"/jobs/{job.id}", json={"progress": 42})
    assert r.status_code == 200
    assert r.json()["progress"] == 42


async def test_patch_job_updates_error_msg(async_client, sample_job_factory):
    """PATCH /jobs/{id} can set an error message."""
    job = await sample_job_factory(status="pending")
    r = await async_client.patch(
        f"/jobs/{job.id}", json={"status": "failed", "error_msg": "disk full"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "failed"
    assert data["error_msg"] == "disk full"


async def test_patch_job_not_found(async_client):
    """PATCH /jobs/{id} returns 404 when job does not exist."""
    r = await async_client.patch(f"/jobs/{uuid.uuid4()}", json={"status": "processing"})
    assert r.status_code == 404


async def test_patch_job_partial_update(async_client, sample_job_factory):
    """PATCH /jobs/{id} with only worker_id leaves other fields unchanged."""
    job = await sample_job_factory(status="pending")
    r = await async_client.patch(f"/jobs/{job.id}", json={"worker_id": "w-99"})
    assert r.status_code == 200
    data = r.json()
    assert data["worker_id"] == "w-99"
    assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# 5. DELETE /jobs/{id}
# ---------------------------------------------------------------------------


async def test_delete_pending_job_succeeds(async_client, sample_job_factory):
    """DELETE /jobs/{id} on a pending job returns success."""
    job = await sample_job_factory(status="pending")
    r = await async_client.delete(f"/jobs/{job.id}")
    assert r.status_code == 200
    assert "deleted" in r.json()["detail"].lower()


async def test_delete_pending_job_removes_from_db(
    async_client, sample_job_factory, db_session
):
    """After DELETE, the job record is gone from the database."""
    from sqlalchemy import select

    job = await sample_job_factory(status="pending")
    await async_client.delete(f"/jobs/{job.id}")
    result = await db_session.execute(select(Job).where(Job.id == job.id))
    assert result.scalar_one_or_none() is None


async def test_delete_processing_job_returns_400(async_client, sample_job_factory):
    """DELETE /jobs/{id} on a processing job returns 400."""
    job = await sample_job_factory(status="processing")
    r = await async_client.delete(f"/jobs/{job.id}")
    assert r.status_code == 400


async def test_delete_completed_job_returns_400(async_client, sample_job_factory):
    """DELETE /jobs/{id} on a completed job returns 400."""
    job = await sample_job_factory(status="completed")
    r = await async_client.delete(f"/jobs/{job.id}")
    assert r.status_code == 400


async def test_delete_job_not_found(async_client):
    """DELETE /jobs/{id} on unknown UUID returns 404."""
    r = await async_client.delete(f"/jobs/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. GET /workers
# ---------------------------------------------------------------------------


async def test_list_workers_empty(async_client):
    """GET /workers returns empty list when no workers registered."""
    r = await async_client.get("/workers")
    assert r.status_code == 200
    assert r.json()["workers"] == []


async def test_list_workers_returns_all(async_client, db_session):
    """GET /workers returns all registered workers."""
    from datetime import datetime, timezone

    w1 = Worker(
        id="worker-1", status="idle", jobs_done=0, last_seen=datetime.now(timezone.utc)
    )
    w2 = Worker(
        id="worker-2", status="busy", jobs_done=3, last_seen=datetime.now(timezone.utc)
    )
    db_session.add_all([w1, w2])
    await db_session.commit()

    r = await async_client.get("/workers")
    assert r.status_code == 200
    workers = r.json()["workers"]
    assert len(workers) == 2
    ids = {w["id"] for w in workers}
    assert ids == {"worker-1", "worker-2"}


# ---------------------------------------------------------------------------
# 7. GET /workers/{id}
# ---------------------------------------------------------------------------


async def test_get_worker_existing(async_client, db_session):
    """GET /workers/{id} returns worker details for a known worker."""
    from datetime import datetime, timezone

    w = Worker(
        id="w-abc", status="idle", jobs_done=5, last_seen=datetime.now(timezone.utc)
    )
    db_session.add(w)
    await db_session.commit()

    r = await async_client.get("/workers/w-abc")
    assert r.status_code == 200
    assert r.json()["id"] == "w-abc"
    assert r.json()["status"] == "idle"


async def test_get_worker_missing(async_client):
    """GET /workers/{id} for unknown worker raises ResponseValidationError (code bug)."""
    from fastapi.exceptions import ResponseValidationError

    # workers.py returns {"error": "..."} which is incompatible with WorkerResponse schema;
    # FastAPI raises ResponseValidationError before any HTTP response is sent.
    with pytest.raises(ResponseValidationError):
        await async_client.get("/workers/no-such-worker")


# ---------------------------------------------------------------------------
# 8. GET /metrics
# ---------------------------------------------------------------------------


async def test_metrics_empty_state(async_client):
    """GET /metrics returns all zero counts when DB and queue are empty."""
    r = await async_client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["queue_length"] == 0
    assert data["jobs_total"] == 0
    assert data["jobs_completed"] == 0
    assert data["jobs_failed"] == 0
    assert data["jobs_processing"] == 0
    assert data["workers_online"] == 0
    assert data["workers_idle"] == 0
    assert data["workers_busy"] == 0


async def test_metrics_queue_length(async_client, redis_mock):
    """GET /metrics reflects current Redis queue length."""
    redis_mock.rpush("jobs:queue", "job1", "job2", "job3")
    r = await async_client.get("/metrics")
    assert r.status_code == 200
    assert r.json()["queue_length"] == 3


async def test_metrics_job_counts_by_status(async_client, sample_job_factory):
    """GET /metrics counts are correct after inserting jobs of various statuses."""
    await sample_job_factory(status="completed")
    await sample_job_factory(status="completed")
    await sample_job_factory(status="failed")
    await sample_job_factory(status="processing")
    await sample_job_factory(status="pending")

    r = await async_client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["jobs_total"] == 5
    assert data["jobs_completed"] == 2
    assert data["jobs_failed"] == 1
    assert data["jobs_processing"] == 1


async def test_metrics_workers_online_idle_busy(async_client, db_session):
    """GET /metrics reflects worker counts split by idle/busy."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Worker(id="m-w1", status="idle", jobs_done=0, last_seen=now),
            Worker(id="m-w2", status="idle", jobs_done=0, last_seen=now),
            Worker(id="m-w3", status="busy", jobs_done=1, last_seen=now),
        ]
    )
    await db_session.commit()

    r = await async_client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["workers_online"] == 3
    assert data["workers_idle"] == 2
    assert data["workers_busy"] == 1


# ---------------------------------------------------------------------------
# 9. scheduler.enqueue_job unit test (not via endpoint)
# ---------------------------------------------------------------------------


async def test_scheduler_enqueue_pushes_to_correct_key():
    """JobScheduler.enqueue_job pushes JSON to the configured Redis list key."""
    from core.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = fakeredis.FakeRedis(decode_responses=True)
    scheduler = JobScheduler(r, "custom:queue")

    async with maker() as session:
        job = Job(
            id=uuid.uuid4(),
            type=JobType.convert_video,
            input_path="/src/movie.mkv",
            params={"codec": "h264"},
        )
        session.add(job)
        await session.flush()
        result = await scheduler.enqueue_job(session, job)

    assert result is True
    assert r.llen("custom:queue") == 1

    payload = json.loads(r.lrange("custom:queue", 0, -1)[0])
    assert payload["type"] == "convert_video"
    assert payload["input_path"] == "/src/movie.mkv"
    assert payload["params"] == {"codec": "h264"}
    assert "id" in payload

    await engine.dispose()


async def test_scheduler_enqueue_sets_status_queued():
    """enqueue_job transitions Job.status to 'queued'."""
    from core.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = fakeredis.FakeRedis(decode_responses=True)
    scheduler = JobScheduler(r, "jobs:queue")

    async with maker() as session:
        job = Job(
            id=uuid.uuid4(),
            type=JobType.thumbnail,
            input_path="/x/y.mp4",
            params={},
        )
        session.add(job)
        await session.flush()
        await scheduler.enqueue_job(session, job)
        assert job.status == JobStatus.queued

    await engine.dispose()


async def test_scheduler_enqueue_multiple_jobs():
    """enqueue_job called twice pushes two items in order."""
    from core.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = fakeredis.FakeRedis(decode_responses=True)
    scheduler = JobScheduler(r, "jobs:queue")

    async with maker() as session:
        for _ in range(3):
            job = Job(
                id=uuid.uuid4(),
                type=JobType.extract_audio,
                input_path="/a.mp4",
                params={},
            )
            session.add(job)
            await session.flush()
            await scheduler.enqueue_job(session, job)

    assert r.llen("jobs:queue") == 3
    await engine.dispose()


# ---------------------------------------------------------------------------
# 10. Invalid input — POST /jobs with missing required fields
# ---------------------------------------------------------------------------


async def test_create_job_missing_type(async_client):
    """POST /jobs without 'type' returns 422."""
    r = await async_client.post("/jobs", json={"input_path": "/a/b.mp4"})
    assert r.status_code == 422


async def test_create_job_missing_input_path(async_client):
    """POST /jobs without 'input_path' returns 422."""
    r = await async_client.post("/jobs", json={"type": "thumbnail"})
    assert r.status_code == 422


async def test_create_job_empty_body(async_client):
    """POST /jobs with empty JSON object returns 422."""
    r = await async_client.post("/jobs", json={})
    assert r.status_code == 422


async def test_create_job_invalid_type_value(async_client):
    """POST /jobs with unknown job type returns 422."""
    r = await async_client.post(
        "/jobs", json={"type": "unknown_type", "input_path": "/a.mp4"}
    )
    assert r.status_code == 422


async def test_create_job_params_defaults_to_empty(async_client):
    """POST /jobs without 'params' uses empty dict default."""
    r = await async_client.post(
        "/jobs", json={"type": "thumbnail", "input_path": "/a.mp4"}
    )
    assert r.status_code == 200
    assert r.json()["params"] == {}
