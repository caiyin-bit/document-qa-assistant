"""Local BGE embedder wrapping sentence-transformers.

bge-large-zh-v1.5 官方建议: 查询要加 instruction 前缀, 被检索的 passage 不加.
MVP 简化: 双侧都不加前缀(差异在一致性上抵消, 足够 MVP 用).

Threading: every encode call runs through `_executor` (max_workers=1) so
that (a) the asyncio event loop is never blocked by torch.encode, and
(b) concurrent callers in the same process serialize through one queue
instead of competing for the same SentenceTransformer instance.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property

from sentence_transformers import SentenceTransformer


class BgeEmbedder:
    def __init__(self, model_path: str = "BAAI/bge-large-zh-v1.5", device: str = "cpu") -> None:
        self._model_path = model_path
        self._device = device
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge")

    @cached_property
    def _model(self) -> SentenceTransformer:
        return SentenceTransformer(self._model_path, device=self._device)

    # --- sync entry points (internal helpers — do not call from async paths) ---

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(
            text, normalize_embeddings=True, convert_to_numpy=True
        )
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=16
        )
        return [v.tolist() for v in vecs]

    def encode_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    # --- async entry points (use these from async code) ---

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.embed_batch, texts)

    async def encode_one_async(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self.encode_one, text)

    def close(self, *, wait: bool = False) -> None:
        """Shutdown the executor.

        cancel_futures=True drops queued-but-not-started encodes. The
        currently-running batch (if any) finishes naturally — torch
        can't be interrupted mid-tensor-op.

        wait=False (default): return immediately. The worker thread
            keeps running until its in-flight batch completes; process
            exit is delayed by that thread but our caller is not.
        wait=True: block until the in-flight batch finishes. Use only
            where draining is verifiable (e.g. test fixtures).
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)
