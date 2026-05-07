import json
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


class CacheService:
    """Small JSON helper around Redis."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or get_redis()

    async def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        value = await self.redis.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(self, key: str, value: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        await self.redis.set(key, json.dumps(value, default=str), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

