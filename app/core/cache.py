import json
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the module-level singleton Redis client, creating it on first call.

    Uses Redis.from_url with decode_responses=True so all responses come back as str
    rather than bytes, which is required for json.loads() to work without extra decoding.
    Thread-safe for asyncio (single event loop; no concurrent init race).
    """
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


class CacheService:
    """Small JSON helper around Redis for typed get/set/delete operations."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or get_redis()

    async def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        """Return the JSON-deserialised value for key, or None if the key is absent or expired.

        Dry run:
            key="summary:client:UUID-1", Redis has value '{"actors":[...]}'
            → {"actors": [...]}
        Dry run (key missing or expired):
            → None
        """
        value = await self.redis.get(key)
        if value is None:
            return None
        return json.loads(value)

    async def set_json(self, key: str, value: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        """Serialise value to JSON and write it to Redis with the given TTL.

        default=str in json.dumps handles UUID and datetime objects that are not
        JSON-serialisable by default, converting them to their string representations.

        Dry run:
            key="summary:client:UUID-1", value={"actors":[]}, ttl_seconds=3600
            → SET "summary:client:UUID-1" '{"actors":[]}' EX 3600
        """
        await self.redis.set(key, json.dumps(value, default=str), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        """Remove a key from Redis. Silent no-op if the key does not exist.

        Dry run:
            key="auth:blocklist:jti-1" → DEL "auth:blocklist:jti-1"
        """
        await self.redis.delete(key)

    async def ping(self) -> bool:
        """Send a PING to Redis and return True if the response is PONG.

        Used by the /ready health probe to confirm Redis is reachable.

        Dry run (Redis up)   → True
        Dry run (Redis down) → raises RedisError (caller handles it)
        """
        return bool(await self.redis.ping())

