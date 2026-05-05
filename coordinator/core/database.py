import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from .config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database session"""
    async with async_session_maker() as session:
        yield session


_PG_MIGRATIONS = (
    # Idempotent additions — safe to re-run on existing databases.
    "ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'extract_metadata'",
    "ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'classify_output'",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal'",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_metadata JSONB DEFAULT '{}'::jsonb",
)


async def _apply_pg_migrations() -> None:
    """Bring an existing Postgres schema up to date with the model.

    create_all only creates missing tables, not missing columns or enum values.
    These ALTERs cover the gap so already-deployed databases pick up new fields
    without a manual drop. Each statement is idempotent (IF NOT EXISTS).
    """
    for stmt in _PG_MIGRATIONS:
        try:
            async with engine.connect() as conn:
                await conn.execute(text(stmt))
                await conn.commit()
        except Exception as exc:
            logger.warning("Migration step skipped (%s): %s", stmt, exc)


async def init_db() -> None:
    """Initialize database tables (and patch existing schemas in place)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if engine.dialect.name == "postgresql":
        await _apply_pg_migrations()


async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()
