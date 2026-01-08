from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from loguru import logger


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
