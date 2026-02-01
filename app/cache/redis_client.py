from typing import Optional

from redis.asyncio import Redis

from app.core.config import get_settings


def get_redis() -> Optional[Redis]:
    settings = get_settings()
    if not settings.redis_url:
        return None
    return Redis.from_url(settings.redis_url, decode_responses=True)
