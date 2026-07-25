"""T10.8 soft topic preference — pure re-rank + find_similar wiring."""

from unittest.mock import MagicMock, patch

import numpy as np

from storage.similarity import apply_soft_topic_prefer, find_similar


def _row(post_id: str, niche: str | None, distance: float) -> dict:
    return {
        "post_id": post_id,
        "niche": niche,
        "cosine_distance": distance,
        "content": f"content-{post_id}",
    }


def test_apply_soft_topic_prefer_raises_matching_niche():
    rows = [
        _row("a", "sports", 0.01),
        _row("b", "fintech", 0.20),
        _row("c", "fintech", 0.05),
        _row("d", "career", 0.02),
    ]
    out = apply_soft_topic_prefer(rows, "fintech", limit=3)
    assert [r["post_id"] for r in out] == ["c", "b", "a"]


def test_apply_soft_topic_prefer_no_niche_preserves_order_truncated():
    rows = [
        _row("a", "sports", 0.01),
        _row("b", "fintech", 0.20),
        _row("c", None, 0.05),
    ]
    out = apply_soft_topic_prefer(rows, None, limit=2)
    assert [r["post_id"] for r in out] == ["a", "b"]


def test_apply_soft_topic_prefer_invalid_niche_preserves_order():
    rows = [
        _row("a", "sports", 0.01),
        _row("b", "fintech", 0.20),
    ]
    out = apply_soft_topic_prefer(rows, "not_a_real_niche", limit=10)
    assert [r["post_id"] for r in out] == ["a", "b"]


def test_apply_soft_topic_prefer_empty_and_zero_limit():
    assert apply_soft_topic_prefer([], "fintech", 5) == []
    assert apply_soft_topic_prefer([_row("a", "fintech", 0.1)], "fintech", 0) == []


def test_apply_soft_topic_prefer_does_not_drop_other_niches():
    """Thin niche: still fill limit from global neighbors after matches."""
    rows = [
        _row("near", "sports", 0.01),
        _row("match", "fintech", 0.50),
        _row("mid", "career", 0.10),
    ]
    out = apply_soft_topic_prefer(rows, "fintech", limit=3)
    assert len(out) == 3
    assert out[0]["post_id"] == "match"
    assert {r["post_id"] for r in out} == {"match", "near", "mid"}


@patch("storage.similarity._find_similar_query")
def test_find_similar_soft_prefer_overfetches_then_truncates(mock_query):
    mock_query.return_value = [
        _row("a", "sports", 0.01),
        _row("b", "fintech", 0.30),
        _row("c", "career", 0.02),
        _row("d", "fintech", 0.15),
        _row("e", "health", 0.03),
        _row("f", "marketing", 0.04),
    ]
    conn = MagicMock()
    vec = np.zeros(8)
    out = find_similar(
        conn,
        vec,
        limit=2,
        prefer_niche="fintech",
        soft_topic_prefer=True,
        overfetch_factor=3,
    )
    assert mock_query.call_args[0][2] == 6  # limit * 3
    assert [r["post_id"] for r in out] == ["d", "b"]


@patch("storage.similarity._find_similar_query")
def test_find_similar_without_prefer_uses_limit(mock_query):
    mock_query.return_value = [_row("a", "sports", 0.01), _row("b", "fintech", 0.02)]
    out = find_similar(MagicMock(), np.zeros(4), limit=2, prefer_niche=None)
    assert mock_query.call_args[0][2] == 2
    assert [r["post_id"] for r in out] == ["a", "b"]


@patch("storage.similarity._find_similar_query")
def test_find_similar_soft_prefer_off_skips_rerank(mock_query):
    mock_query.return_value = [
        _row("a", "sports", 0.01),
        _row("b", "fintech", 0.50),
    ]
    out = find_similar(
        MagicMock(),
        np.zeros(4),
        limit=2,
        prefer_niche="fintech",
        soft_topic_prefer=False,
    )
    assert mock_query.call_args[0][2] == 2
    assert [r["post_id"] for r in out] == ["a", "b"]


def test_vector_store_reexports_find_similar():
    from storage.vector_store import find_similar as exported
    from storage.similarity import find_similar as canonical

    assert exported is canonical
