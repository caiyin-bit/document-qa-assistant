"""Local BGE embedder wrapping sentence-transformers.

bge-large-zh-v1.5 官方建议:查询要加 instruction 前缀,被检索的 passage 不加.
MVP 简化:双侧都不加前缀(差异在一致性上抵消,足够 MVP 用).
"""

from __future__ import annotations

from functools import cached_property

from sentence_transformers import SentenceTransformer


class BgeEmbedder:
    def __init__(self, model_path: str = "BAAI/bge-large-zh-v1.5", device: str = "cpu") -> None:
        self._model_path = model_path
        self._device = device

    @cached_property
    def _model(self) -> SentenceTransformer:
        return SentenceTransformer(self._model_path, device=self._device)

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
