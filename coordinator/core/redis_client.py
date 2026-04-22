import redis
import redis.asyncio as aioredis
from typing import Optional
from .config import get_settings


class RedisClient:
    """Redis connection pool for coordinator"""

    _instance: Optional[redis.Redis] = None
    _async_instance: Optional[aioredis.Redis] = None

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
    def get_async_connection(cls) -> aioredis.Redis:
        """Get or create async Redis connection (used by websocket pub/sub)"""
        if cls._async_instance is None:
            settings = get_settings()
            cls._async_instance = aioredis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
            )
        return cls._async_instance

    @classmethod
    def close(cls) -> None:
        """Close Redis connection"""
        if cls._instance:
            cls._instance.close()
            cls._instance = None

    @classmethod
    async def aclose(cls) -> None:
        """Close async Redis connection"""
        if cls._async_instance:
            await cls._async_instance.aclose()
            cls._async_instance = None


def get_redis() -> redis.Redis:
    """Dependency for getting Redis connection"""
    return RedisClient.get_connection()


def get_async_redis() -> aioredis.Redis:
    """Dependency for getting async Redis connection"""
    return RedisClient.get_async_connection()
