"""Async API + executor lifecycle for BgeEmbedder."""
import asyncio
import time
import pytest
import numpy as np

from src.embedding.bge_embedder import BgeEmbedder


class _FakeModel:
    """Stand-in for SentenceTransformer; records call thread + sleeps."""
    def __init__(self):
        self.call_threads: list[str] = []
        self.encode_delay = 0.0

    def encode(self, texts, **kw):
        import threading
        self.call_threads.append(threading.current_thread().name)
        if self.encode_delay:
            time.sleep(self.encode_delay)
        # Mimic shape: 2D numpy array for batch, 1D for single
        if isinstance(texts, list):
            return np.array([[0.1] * 1024 for _ in texts])
        return np.array([0.1] * 1024)


def _make_embedder(fake: _FakeModel) -> BgeEmbedder:
    e = BgeEmbedder(model_path="dummy", device="cpu")
    # Bypass cached_property to inject the fake
    e.__dict__["_model"] = fake
    return e


@pytest.mark.asyncio
async def test_embed_batch_async_returns_correct_shape():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    try:
        out = await emb.embed_batch_async(["a", "b", "c"])
        assert len(out) == 3
        assert all(len(v) == 1024 for v in out)
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_encode_one_async_returns_single_vector():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    try:
        out = await emb.encode_one_async("hello")
        assert len(out) == 1024
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_concurrent_encodes_are_serialized_in_one_thread():
    """max_workers=1 means concurrent encode_one_async calls run on the
    SAME thread one after another, never in parallel on the same model."""
    fake = _FakeModel()
    fake.encode_delay = 0.05
    emb = _make_embedder(fake)
    try:
        await asyncio.gather(
            emb.encode_one_async("a"),
            emb.encode_one_async("b"),
            emb.encode_one_async("c"),
        )
        assert len(set(fake.call_threads)) == 1, fake.call_threads
        assert all("bge" in t for t in fake.call_threads)
    finally:
        emb.close(wait=True)


@pytest.mark.asyncio
async def test_close_wait_true_drains_executor():
    fake = _FakeModel()
    emb = _make_embedder(fake)
    await emb.encode_one_async("warm-up")  # spawns the worker thread
    threads_before = list(emb._executor._threads)
    emb.close(wait=True)
    # After wait=True shutdown, threads should have exited
    for t in threads_before:
        t.join(timeout=2.0)
        assert not t.is_alive(), f"thread {t.name} still alive after close(wait=True)"


@pytest.mark.asyncio
async def test_close_wait_false_returns_quickly():
    fake = _FakeModel()
    fake.encode_delay = 0.5  # in-flight batch will take 0.5s
    emb = _make_embedder(fake)
    task = asyncio.create_task(emb.embed_batch_async(["x"]))
    await asyncio.sleep(0.05)  # let the batch start
    t0 = time.monotonic()
    emb.close(wait=False)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"close(wait=False) blocked for {elapsed:.3f}s"
    # The in-flight task still completes
    await task
    # Final cleanup so pytest doesn't see lingering thread
    emb.close(wait=True)
