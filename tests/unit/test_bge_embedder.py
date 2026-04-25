"""Tests for BGE local embedder."""

import numpy as np
import pytest

from src.embedding.bge_embedder import BgeEmbedder


@pytest.fixture(scope="module")
def embedder() -> BgeEmbedder:
    # NOTE: first run downloads ~1.3GB from HuggingFace.
    return BgeEmbedder(model_path="BAAI/bge-large-zh-v1.5", device="cpu")


def test_embed_returns_1024_dim_vector(embedder: BgeEmbedder):
    vec = embedder.embed("张三是做外贸的,老婆全职带俩娃")
    assert isinstance(vec, list)
    assert len(vec) == 1024
    assert all(isinstance(x, float) for x in vec[:5])


def test_embed_batch(embedder: BgeEmbedder):
    vecs = embedder.embed_batch(["文本一", "文本二", "文本三"])
    assert len(vecs) == 3
    assert all(len(v) == 1024 for v in vecs)


def test_similar_texts_have_higher_cosine(embedder: BgeEmbedder):
    a = np.array(embedder.embed("外贸商人,已婚有孩子"))
    b = np.array(embedder.embed("做外贸的,有家庭有娃"))
    c = np.array(embedder.embed("登山爱好者,单身"))
    cos_ab = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    cos_ac = float(a @ c / (np.linalg.norm(a) * np.linalg.norm(c)))
    assert cos_ab > cos_ac
