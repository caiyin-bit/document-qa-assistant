"""Arq WorkerSettings entry point.

Run from container as:
    uv run arq src.worker.main.WorkerSettings

Spec: docs/superpowers/specs/2026-04-26-ingestion-worker-design.md §3.2.
"""
from __future__ import annotations

import logging

from arq.worker import func
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import load_config
from src.db.session import make_engine, make_sessionmaker
from src.embedding.bge_embedder import BgeEmbedder
from src.worker.jobs import INGEST_MAX_TRIES, INGEST_TIMEOUT, ingest_document
from src.worker.redis_pool import make_redis_settings

log = logging.getLogger(__name__)


async def _on_startup(ctx: dict) -> None:
    """Build per-process singletons and attach them to ctx so jobs reuse them."""
    cfg = load_config()
    engine = make_engine(cfg.db.url)
    sm: async_sessionmaker = make_sessionmaker(engine)
    embedder = BgeEmbedder(model_path=cfg.embedding.model_path, device=cfg.embedding.device)

    ctx["engine"] = engine
    ctx["sessionmaker"] = sm
    ctx["embedder"] = embedder
    log.info("worker startup: deps wired (db + embedder)")


async def _on_shutdown(ctx: dict) -> None:
    embedder: BgeEmbedder = ctx.get("embedder")  # type: ignore[assignment]
    if embedder is not None:
        embedder.close(wait=False)
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker shutdown: embedder + engine closed")


class WorkerSettings:
    functions = [
        func(ingest_document, name="ingest_document",
             timeout=INGEST_TIMEOUT, max_tries=INGEST_MAX_TRIES),
    ]
    redis_settings = make_redis_settings()
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 1
    keep_result = 60
