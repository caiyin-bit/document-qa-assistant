"""Unit tests for RRF fusion helper."""
from __future__ import annotations

import pytest

from src.core.memory_service import _rrf_fuse_scores


def test_rrf_simple_two_stages():
    stage_a = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    stage_b = [{"chunk_id": "b"}, {"chunk_id": "d"}, {"chunk_id": "a"}]
    scores = _rrf_fuse_scores([stage_a, stage_b], k=60)
    assert pytest.approx(scores["a"], rel=1e-9) == 1 / 61 + 1 / 63
    assert pytest.approx(scores["b"], rel=1e-9) == 1 / 62 + 1 / 61
    assert pytest.approx(scores["c"], rel=1e-9) == 1 / 63
    assert pytest.approx(scores["d"], rel=1e-9) == 1 / 62


def test_rrf_dedups_within_stage():
    """Same chunk appearing twice in one stage contributes only its best rank."""
    duped = [{"chunk_id": "a"}, {"chunk_id": "a"}, {"chunk_id": "b"}]
    scores = _rrf_fuse_scores([duped], k=60)
    assert pytest.approx(scores["a"], rel=1e-9) == 1 / 61
    # rank slot 2 belongs to the dup'd 'a' and is skipped; 'b' is rank 3
    assert pytest.approx(scores["b"], rel=1e-9) == 1 / 63


def test_rrf_caller_sorts_with_id_tiebreak():
    """When two chunks tie on score, caller's (score DESC, id ASC) sort wins."""
    stage_a = [{"chunk_id": "z"}, {"chunk_id": "a"}]
    stage_b = [{"chunk_id": "a"}, {"chunk_id": "z"}]
    scores = _rrf_fuse_scores([stage_a, stage_b], k=60)
    fused = sorted(scores, key=lambda cid: (-scores[cid], cid))
    assert pytest.approx(scores["a"], rel=1e-9) == scores["z"]
    assert fused == ["a", "z"]


def test_rrf_empty_input_returns_empty_dict():
    assert _rrf_fuse_scores([], k=60) == {}
    assert _rrf_fuse_scores([[], []], k=60) == {}


def test_rrf_three_stages_generalization():
    s1 = [{"chunk_id": "x"}]
    s2 = [{"chunk_id": "y"}]
    s3 = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    scores = _rrf_fuse_scores([s1, s2, s3], k=60)
    assert pytest.approx(scores["x"], rel=1e-9) == 1 / 61 + 1 / 61
    assert pytest.approx(scores["y"], rel=1e-9) == 1 / 61 + 1 / 62
