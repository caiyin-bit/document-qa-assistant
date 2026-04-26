"""Shared Redis connection settings used by both backend (enqueue side)
and worker (consume side)."""
from __future__ import annotations

import os

from arq.connections import RedisSettings


def make_redis_settings() -> RedisSettings:
    """Build RedisSettings from REDIS_URL env. Raise if unset — fail-fast
    behavior matches Config in src/main.py."""
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL env var is required for ingestion worker")
    return RedisSettings.from_dsn(url)
