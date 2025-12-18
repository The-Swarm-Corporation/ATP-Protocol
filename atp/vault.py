from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import redis.asyncio as redis
from loguru import logger


class RedisVault:
    """Distributed job vault using Redis with automatic TTL expiration."""

    def __init__(self, redis_url: str, default_ttl: int = 600):
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self._client: Optional[redis.Redis] = None
        self._prefix = "atp:job:"

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self._client = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._client.ping()
        logger.info(f"Connected to Redis at {self.redis_url}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Disconnected from Redis")

    async def store(
        self, job_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        """Store job data with TTL expiration."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = f"{self._prefix}{job_id}"
        ttl = ttl or self.default_ttl
        serialized = json.dumps(data)
        await self._client.setex(key, ttl, serialized)

    async def retrieve(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job data by ID."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = f"{self._prefix}{job_id}"
        data = await self._client.get(key)
        if data:
            return json.loads(data)
        return None

    async def delete(self, job_id: str) -> bool:
        """Delete job data and return True if it existed."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = f"{self._prefix}{job_id}"
        result = await self._client.delete(key)
        return result > 0

    async def pop(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete job data atomically."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        key = f"{self._prefix}{job_id}"
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()

        if results[0]:
            return json.loads(results[0])
        return None


class InMemoryVault:
    """In-process job vault with TTL expiration (for local dev/testing).

    Note: data is not shared across processes and is lost on restart.
    """

    def __init__(self, default_ttl: int = 600):
        self.default_ttl = default_ttl
        self._lock = asyncio.Lock()
        # key: job_id -> {"data": dict, "expires_at": float}
        self._store: Dict[str, Dict[str, Any]] = {}

    async def connect(self) -> None:
        logger.warning(
            "Using in-memory job vault (no Redis). Jobs will be lost on restart."
        )

    async def disconnect(self) -> None:
        return None

    def _is_expired(self, expires_at: float) -> bool:
        import time

        return time.time() >= expires_at

    async def store(
        self, job_id: str, data: Dict[str, Any], ttl: Optional[int] = None
    ) -> None:
        import time

        ttl = ttl or self.default_ttl
        expires_at = time.time() + ttl
        async with self._lock:
            self._store[job_id] = {"data": data, "expires_at": expires_at}

    async def retrieve(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            entry = self._store.get(job_id)
            if not entry:
                return None
            if self._is_expired(entry["expires_at"]):
                self._store.pop(job_id, None)
                return None
            return entry["data"]

    async def delete(self, job_id: str) -> bool:
        async with self._lock:
            existed = job_id in self._store
            self._store.pop(job_id, None)
            return existed

    async def pop(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            entry = self._store.get(job_id)
            if not entry:
                return None
            if self._is_expired(entry["expires_at"]):
                self._store.pop(job_id, None)
                return None
            self._store.pop(job_id, None)
            return entry["data"]
