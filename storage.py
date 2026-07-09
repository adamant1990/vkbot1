"""Хранилище состояний на Redis"""

import redis.asyncio as redis
from config import settings
import json
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

class RedisStorage:
    """Хранилище на Redis с тем же интерфейсом, что и старый StorageProxy"""
    
    def __init__(self):
        self._redis = None
    
    async def _get_redis(self):
        if self._redis is None:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis
    
    def _make_key(self, key: str) -> str:
        return f"ctx:{key}"
    
    async def get(self, key: str, default=None):
        r = await self._get_redis()
        value = await r.get(self._make_key(key))
        if value is None:
            return default
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    
    async def set(self, key: str, value, expire: int = 3600):
        """Устанавливает значение с TTL 1 час (по умолчанию)"""
        r = await self._get_redis()
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, default=str)
        await r.set(self._make_key(key), value, ex=expire)
    
    async def delete(self, key: str):
        r = await self._get_redis()
        await r.delete(self._make_key(key))
    
    def get_sync(self, key: str, default=None):
        """Синхронный метод для совместимости (используется редко)"""
        import warnings
        warnings.warn("Sync get on Redis storage — consider using async get", RuntimeWarning)
        return default
    
    async def close(self):
        if self._redis:
            await self._redis.close()
            self._redis = None

# Глобальный экземпляр
ctx = RedisStorage()
