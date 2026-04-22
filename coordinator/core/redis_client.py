import redis
from typing import Optional
from .config import get_settings


class RedisClient:
    """Redis connection pool for coordinator"""

    _instance: Optional[redis.Redis] = None

    @classmethod
    def get_connection(cls) -> redis.Redis:
        """Get or create Redis connection"""
        if cls._instance is None:
            settings = get_settings()
            cls._instance = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
        return cls._instance

    @classmethod
    def close(cls) -> None:
        """Close Redis connection"""
        if cls._instance:
            cls._instance.close()
            cls._instance = None


def get_redis() -> redis.Redis:
    """Dependency for getting Redis connection"""
    return RedisClient.get_connection()
