"""Local BGE cross-encoder reranker.

Stage between vector recall and tool result return. Vector recall (BGE
embedder + pgvector cosine) gives a coarse top-k candidate set; the
reranker re-scores each (query, passage) pair with a true cross-encoder
and returns the top-n by relevance. Cross-encoder relevance is more
accurate than bi-encoder cosine because the model reads query and
passage jointly, but is much slower (cannot pre-compute) — so it only
runs on the ~16-doc shortlist, not the whole index.

Threading mirrors `BgeEmbedder`: every call goes through a single-
thread executor so torch never blocks the event loop and concurrent
callers serialise through one queue.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property

from sentence_transformers import CrossEncoder


class BgeReranker:
    def __init__(
        self,
        model_path: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="bge-rerank",
        )

    @cached_property
    def _model(self) -> CrossEncoder:
        return CrossEncoder(self._model_path, device=self._device)

    def score_pairs(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        pairs = [(query, p) for p in passages]
        scores = self._model.predict(pairs, batch_size=8, show_progress_bar=False)
        return [float(s) for s in scores]

    async def score_pairs_async(
        self, query: str, passages: list[str],
    ) -> list[float]:
        if not passages:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, self.score_pairs, query, passages,
        )

    def close(self, *, wait: bool = False) -> None:
        """Same semantics as BgeEmbedder.close: drop queued, let in-flight
        finish (torch can't be interrupted mid-tensor-op)."""
        self._executor.shutdown(wait=wait, cancel_futures=True)
