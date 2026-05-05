from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Coordinator configuration from environment variables"""

    # API
    coordinator_host: str = "0.0.0.0"
    coordinator_port: int = 8000

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "multimedia_db"
    postgres_user: str = "admin"
    postgres_password: str = "secret123"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_queue_key: str = "jobs:queue"
    redis_progress_channel: str = "jobs:progress"

    @property
    def priority_queue_keys(self) -> list[str]:
        """Redis list keys ordered from highest to lowest priority."""
        return [
            f"{self.redis_queue_key}:high",
            f"{self.redis_queue_key}:normal",
            f"{self.redis_queue_key}:low",
        ]

    def queue_key_for_priority(self, priority: str) -> str:
        """Return the Redis list key for a given priority label."""
        if priority not in ("high", "normal", "low"):
            priority = "normal"
        return f"{self.redis_queue_key}:{priority}"

    # Application
    log_level: str = "info"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def database_url(self) -> str:
        """PostgreSQL connection string"""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection string"""
        return f"redis://{self.redis_host}:{self.redis_port}"


def get_settings() -> Settings:
    """Get application settings"""
    return Settings()
