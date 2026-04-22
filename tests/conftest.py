"""Shared fixtures for coordinator unit tests."""
import sys
import uuid
import pytest
import fakeredis
import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Ensure coordinator package is importable
sys.path.insert(0, "coordinator")

from main import app
from core.database import get_db, Base
from core.redis_client import get_redis
from models.job import Job, Worker, JobStatus, JobType


# ---------------------------------------------------------------------------
# Event loop + asyncio_mode are configured via pytest.ini / pyproject.toml.
# pytest-asyncio 1.x honours asyncio_mode = "auto" set in pytest.ini.
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_engine():
    """In-memory SQLite engine with all tables created fresh per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Single AsyncSession for direct ORM operations in tests."""
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
def redis_mock():
    """Sync FakeRedis instance (matches coordinator's sync redis.Redis usage)."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def async_client(db_engine, redis_mock):
    """AsyncClient bound to the FastAPI app with DB and Redis overrides active."""
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    def override_get_redis():
        return redis_mock

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def sample_job_factory(db_session):
    """Factory that inserts Job records into the test DB and returns them."""
    created = []

    async def _make(
        job_type: str = "thumbnail",
        input_path: str = "/data/sample.mp4",
        status: str = "pending",
        worker_id: str = None,
        params: dict = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4(),
            type=JobType(job_type),
            input_path=input_path,
            status=JobStatus(status),
            worker_id=worker_id,
            params=params or {},
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)
        created.append(job)
        return job

    return _make
