import time
from typing import Optional
from urllib.parse import quote_plus

from azure.identity.aio import DefaultAzureCredential
from azure.keyvault.secrets.aio import SecretClient
from redis.asyncio import Redis

from app.core.config import get_settings

_cached_password: Optional[str] = None
_cached_password_at: float = 0.0


async def _get_redis_password() -> Optional[str]:
    global _cached_password, _cached_password_at
    settings = get_settings()
    if not settings.azure_key_vault_url or not settings.azure_redis_password_secret_name:
        return None

    now = time.time()
    if _cached_password and now - _cached_password_at < settings.redis_password_cache_ttl_seconds:
        return _cached_password

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=settings.azure_key_vault_url, credential=credential)
    try:
        secret = await client.get_secret(settings.azure_redis_password_secret_name)
        _cached_password = secret.value
        _cached_password_at = now
        return _cached_password
    finally:
        await client.close()
        await credential.close()


async def get_redis() -> Optional[Redis]:
    settings = get_settings()
    if settings.redis_url:
        return Redis.from_url(settings.redis_url, decode_responses=True)

    if not settings.azure_redis_host:
        return None

    password = await _get_redis_password()
    if not password:
        raise RuntimeError("Azure Redis password could not be retrieved from Key Vault.")

    scheme = "rediss" if settings.azure_redis_ssl else "redis"
    encoded_password = quote_plus(password)
    redis_url = f"{scheme}://:{encoded_password}@{settings.azure_redis_host}:{settings.azure_redis_port}/0"
    return Redis.from_url(redis_url, decode_responses=True, ssl=settings.azure_redis_ssl)
