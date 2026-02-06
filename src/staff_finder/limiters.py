"""Concurrency limiters for async operations."""

import asyncio
from dataclasses import dataclass

from .config import Settings  # type: ignore


@dataclass
class Limiters:
    """Semaphore-based concurrency limiters."""
    sem_schools: asyncio.Semaphore
    sem_jina: asyncio.Semaphore
    sem_openai: asyncio.Semaphore

    @classmethod
    def from_settings(cls, cfg: Settings) -> "Limiters":
        """Create limiters from settings."""
        return cls(
            sem_schools=asyncio.Semaphore(max(1, cfg.max_concurrent_schools)),
            sem_jina=asyncio.Semaphore(max(1, cfg.max_concurrent_jina)),
            sem_openai=asyncio.Semaphore(max(1, cfg.max_concurrent_openai)),
        )
