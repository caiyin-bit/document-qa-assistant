"""FastAPI app factory.

Production entrypoint (uvicorn --factory mode, fails fast on bad config):
    uvicorn --factory src.main:make_app_default --host 0.0.0.0 --port 8000

Test entrypoint:
    app = create_app(deps=...)  # with mocked dependencies
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.chat import ChatDependencies, ConvSettings, make_router
from src.api.documents import make_documents_router
from src.config import Config, load_config
from src.core.persona_loader import PersonaLoader
from src.core.summarizer import Summarizer
from src.db.session import make_engine, make_sessionmaker
from src.embedding.bge_embedder import BgeEmbedder
from src.llm.kimi_client import KimiClient


def create_app(deps: ChatDependencies) -> FastAPI:
    app = FastAPI(title="Document QA Assistant")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "OPTIONS"],
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
    summarizer = Summarizer(llm=llm)
    settings = ConvSettings(
        max_tool_iterations=cfg.conversation.max_tool_iterations,
        compress_trigger_threshold=cfg.memory.compress_trigger_threshold,
        compress_keep_recent=cfg.memory.compress_keep_recent,
        retrieve_top_k=cfg.memory.retrieve_top_k,
        similarity_threshold=cfg.memory.similarity_threshold,
    )
    return ChatDependencies(
        sessionmaker=sm,
        persona=persona,
        embedder=embedder,
        llm=llm,
        summarizer=summarizer,
        default_user_id=cfg.app_user.default_user_id,
        settings=settings,
    )


def make_app_default() -> FastAPI:
    """Build the production app on demand. Raises immediately if config is
    invalid — no silent fallback. Use with `uvicorn --factory`.
    """
    deps = _production_deps()
    app = create_app(deps)

    @app.on_event("startup")
    async def _cleanup_stale_documents_on_startup():
        from src.ingest.ingestion import cleanup_stale_documents
        from src.core.memory_service import MemoryService
        async with deps.sessionmaker() as db:
            mem = MemoryService(db)
            await cleanup_stale_documents(mem)

    return app
