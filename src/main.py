"""FastAPI app factory.

Production entrypoint (uvicorn --factory mode, fails fast on bad config):
    uvicorn --factory src.main:make_app_default --host 0.0.0.0 --port 8000

Test entrypoint:
    app = create_app(deps=...)  # with mocked dependencies
"""

from __future__ import annotations

import os
from functools import lru_cache

from arq import create_pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.chat import ChatDependencies, ConvSettings, make_router
from src.api.documents import make_documents_router
from src.config import Config, load_config
from src.core.persona_loader import PersonaLoader
from src.db.session import make_engine, make_sessionmaker
from src.embedding.bge_embedder import BgeEmbedder
from src.llm.kimi_client import KimiClient
from src.worker.redis_pool import make_redis_settings


def create_app(deps: ChatDependencies) -> FastAPI:
    app = FastAPI(title="Document QA Assistant")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.include_router(make_router(deps))
    app.include_router(make_documents_router(embedder=deps.embedder))
    return app


@lru_cache
def _production_deps() -> ChatDependencies:
    """Wire real implementations from config for production startup.

    Heavy singletons (engine, sessionmaker, embedder, persona, llm) are
    constructed once. The router resolves a fresh AsyncSession per request
    via FastAPI Depends, so multiple concurrent /chat calls don't share
    transaction state.
    """
    cfg: Config = load_config()
    if cfg.app_user.default_user_id is None:
        raise RuntimeError(
            "APP_USER_ID env var missing. Run scripts/seed_demo_user.py first."
        )

    engine = make_engine(cfg.db.url)
    sm = make_sessionmaker(engine)
    embedder = BgeEmbedder(
        model_path=cfg.embedding.model_path, device=cfg.embedding.device
    )
    persona = PersonaLoader(cfg.persona.identity_path, cfg.persona.soul_path)
    llm = KimiClient.from_config(
        base_url=cfg.llm.base_url, api_key=cfg.llm.api_key, model_id=cfg.llm.model_id
    )
    settings = ConvSettings(
        max_tool_iterations=cfg.conversation.max_tool_iterations,
        compress_trigger_threshold=cfg.memory.compress_trigger_threshold,
        compress_keep_recent=cfg.memory.compress_keep_recent,
        retrieve_top_k=cfg.memory.retrieve_top_k,
        similarity_threshold=cfg.memory.similarity_threshold,
    )
    # MIN_SIMILARITY env var overrides config.yaml default (spec §5)
    min_similarity = float(os.environ.get("MIN_SIMILARITY", 0.35))
    top_k = int(os.environ.get("TOP_K", 16))
    return ChatDependencies(
        sessionmaker=sm,
        persona=persona,
        embedder=embedder,
        llm=llm,
        default_user_id=cfg.app_user.default_user_id,
        settings=settings,
        min_similarity=min_similarity,
        top_k=top_k,
    )


def make_app_default() -> FastAPI:
    """Build the production app on demand. Raises immediately if config is
    invalid — no silent fallback. Use with `uvicorn --factory`.
    """
    deps = _production_deps()
    app = create_app(deps)

    _arq_pool_holder: dict = {}

    @app.on_event("startup")
    async def _create_arq_pool():
        pool = await create_pool(make_redis_settings())
        _arq_pool_holder["pool"] = pool
        app.state.arq_pool = pool

    @app.on_event("startup")
    async def _reenqueue_processing_on_startup():
        # Must run AFTER _create_arq_pool — declared after it so FastAPI
        # invokes the hooks in source order.
        from src.api.reaper import reenqueue_processing_documents
        await reenqueue_processing_documents(
            arq_pool=app.state.arq_pool,
            sessionmaker=deps.sessionmaker,
        )

    @app.on_event("shutdown")
    async def _close_arq_pool():
        pool = _arq_pool_holder.get("pool")
        if pool is not None:
            await pool.aclose()

    @app.on_event("shutdown")
    async def _close_embedder_on_shutdown():
        deps.embedder.close(wait=False)

    return app
