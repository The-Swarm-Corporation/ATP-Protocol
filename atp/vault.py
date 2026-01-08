from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from loguru import logger


class InMemoryVault:
    """
    In-process job vault with TTL expiration (for local dev/testing).

    This class provides a simple async-safe in-memory storage
    for job data, allowing you to store, retrieve, and expire
    job-related data after a specified time-to-live (TTL).

    Note: Data is not shared across processes and will be lost
    if the process restarts. Intended for local/dev environments only.
    """

    def __init__(self, default_ttl: int = 600):
        """
        Initialize an in-memory job vault.

        Args:
            default_ttl (int): Default time-to-live for entries in seconds.
        """
        self.default_ttl = default_ttl
        self._lock = asyncio.Lock()
        # key: job_id -> {"data": dict, "expires_at": float}
        self._store: Dict[str, Dict[str, Any]] = {}

    async def connect(self) -> None:
        """
        Connect to the vault.

        For the in-memory implementation, this emits a warning and takes no action.
        """
        logger.warning(
            "Using in-memory job vault. Jobs will be lost on restart."
        )

    async def disconnect(self) -> None:
        """
        Disconnect from the vault.

        For the in-memory implementation, this is a no-op.
        """
        return None

    def _is_expired(self, expires_at: float) -> bool:
        """
        Check if the entry with the given expiration timestamp has expired.

        Args:
            expires_at (float): Expiration timestamp (seconds since epoch).

        Returns:
            bool: True if the entry is expired, False otherwise.
        """
        import time

        return time.time() >= expires_at

    async def store(
        self,
        job_id: str,
        data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> None:
        """
        Store job data in the vault with an optional TTL.

        Args:
            job_id (str): Unique identifier for the job.
            data (Dict[str, Any]): Job-related data to store.
            ttl (Optional[int]): Optional time-to-live in seconds; defaults to self.default_ttl.
        """
        import time

        ttl = ttl or self.default_ttl
        expires_at = time.time() + ttl
        async with self._lock:
            self._store[job_id] = {
                "data": data,
                "expires_at": expires_at,
            }

    async def retrieve(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve data for a given job_id if it exists and hasn't expired.

        Args:
            job_id (str): Unique identifier for the job.

        Returns:
            Optional[Dict[str, Any]]: The stored job data, or None if not found or expired.
        """
        async with self._lock:
            entry = self._store.get(job_id)
            if not entry:
                return None
            if self._is_expired(entry["expires_at"]):
                self._store.pop(job_id, None)
                return None
            return entry["data"]

    async def delete(self, job_id: str) -> bool:
        """
        Delete the job entry for the given job_id if it exists.

        Args:
            job_id (str): Unique identifier for the job.

        Returns:
            bool: True if the entry existed and was deleted, False otherwise.
        """
        async with self._lock:
            existed = job_id in self._store
            self._store.pop(job_id, None)
            return existed

    async def pop(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve and remove the job data for the given job_id if it exists and hasn't expired.

        Args:
            job_id (str): Unique identifier for the job.

        Returns:
            Optional[Dict[str, Any]]: The job data if it existed and was valid, else None.
        """
        async with self._lock:
            entry = self._store.get(job_id)
            if not entry:
                return None
            if self._is_expired(entry["expires_at"]):
                self._store.pop(job_id, None)
                return None
            self._store.pop(job_id, None)
            return entry["data"]
