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

    # Worker settings
    worker_heartbeat_interval: int = 5
    worker_max_retries: int = 3
    metrics_port: int = 9100

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
