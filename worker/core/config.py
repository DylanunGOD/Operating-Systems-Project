from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Worker configuration from environment variables"""

    # Identidad del worker
    worker_id: str = "worker-default"

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
        """Redis list keys ordered from highest to lowest priority.

        Worker BLPOPs across all three; Redis returns the first non-empty key,
        which gives us strict priority dispatch with a single round trip.
        """
        return [
            f"{self.redis_queue_key}:high",
            f"{self.redis_queue_key}:normal",
            f"{self.redis_queue_key}:low",
        ]

    # Worker settings
    worker_heartbeat_interval: int = 5
    worker_max_retries: int = 3
    metrics_port: int = 9100

    # Coordinator HTTP API (for registration / heartbeat)
    coordinator_host: str = "coordinator"
    coordinator_port: int = 8000

    @property
    def coordinator_url(self) -> str:
        return f"http://{self.coordinator_host}:{self.coordinator_port}"

    # Storage
    media_input_dir: str = "/media/input"
    media_output_dir: str = "/media/output"

    # Logging
    log_level: str = "info"
    debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


def get_settings() -> Settings:
    """Get application settings"""
    return Settings()
