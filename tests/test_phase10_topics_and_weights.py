"""Unit tests for T10.6 niche mapping and T10.2 weight aggregation."""

from __future__ import annotations

from phase_10.topics import DEFAULT_NICHE, normalize_topic_to_niche
from phase_10.user_niches import (
    compute_user_niche_rows,
    global_weights_from_primaries,
    primary_niche_by_user,
)


def test_normalize_topic_known_aliases() -> None:
    assert normalize_topic_to_niche("fintech payments") == "fintech"
    assert normalize_topic_to_niche("B2B SaaS growth") == "saas_b2b"
    assert normalize_topic_to_niche("job hiring tips") == "career"
    assert normalize_topic_to_niche("AI tools for writers") == "ai_tech"
    assert normalize_topic_to_niche("ai") == "ai_tech"
    assert normalize_topic_to_niche("football weekend") == "sports"
    assert normalize_topic_to_niche("mental health tips") == "health"


def test_normalize_topic_enum_passthrough_and_unknown() -> None:
    assert normalize_topic_to_niche("fintech") == "fintech"
    assert normalize_topic_to_niche("saas_b2b") == "saas_b2b"
    assert normalize_topic_to_niche(None) == DEFAULT_NICHE
    assert normalize_topic_to_niche("") == DEFAULT_NICHE
    assert normalize_topic_to_niche("obscure pottery club") == DEFAULT_NICHE


def test_weights_all_fintech_omits_idle_niches() -> None:
    rows = compute_user_niche_rows(
        [
            ("u1", "fintech"),
            ("u1", "fintech"),
            ("u2", "fintech"),
            ("u3", "fintech"),
        ]
    )
    primaries = primary_niche_by_user(rows)
    weights = global_weights_from_primaries(primaries)
    assert weights == {"fintech": 1.0}
    assert "sports" not in weights


def test_weights_mixed_users_proportional() -> None:
    rows = compute_user_niche_rows(
        [
            ("u1", "fintech"),
            ("u1", "fintech"),
            ("u2", "sports"),
            ("u3", "fintech"),
            ("u4", "marketing"),
        ]
    )
    primaries = primary_niche_by_user(rows)
    assert primaries == {
        "u1": "fintech",
        "u2": "sports",
        "u3": "fintech",
        "u4": "marketing",
    }
    weights = global_weights_from_primaries(primaries)
    assert weights == {
        "fintech": 0.5,
        "marketing": 0.25,
        "sports": 0.25,
    }


def test_primary_niche_tie_breaks_alphabetically() -> None:
    rows = compute_user_niche_rows(
        [
            ("u1", "sports"),
            ("u1", "fintech"),
        ]
    )
    # Equal counts → alphabetical niche name wins.
    assert primary_niche_by_user(rows)["u1"] == "fintech"


def test_no_users_yields_empty_weights() -> None:
    assert global_weights_from_primaries({}) == {}
    assert compute_user_niche_rows([]) == []


def test_apply_niche_on_record() -> None:
    from phase_10.tagging import apply_niche

    out = apply_niche({"topic": "creator economy tips"})
    assert out["niche"] == "creator"
    assert out["topic"] == "creator economy tips"
    out2 = apply_niche({"topic": "x", "niche": "fintech"})
    assert out2["niche"] == "fintech"
    assert out2["topic"] == "x"


def test_apply_niche_tags_other_for_unmatched_topic() -> None:
    from phase_10.tagging import apply_niche

    # Preserve free-text topic under niche=other for future taxonomy expansion.
    out = apply_niche({"topic": "obscure pottery club"})
    assert out["niche"] == DEFAULT_NICHE
    assert out["topic"] == "obscure pottery club"

    empty = apply_niche({"topic": None})
    assert empty["niche"] == DEFAULT_NICHE
    assert empty["topic"] == DEFAULT_NICHE

    already = apply_niche({"topic": "random", "niche": "other"})
    assert already["niche"] == DEFAULT_NICHE
    assert already["topic"] == "random"
