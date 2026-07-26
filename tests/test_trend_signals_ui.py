"""Unit tests for Draft evaluator Google Trends panel helpers (no live pytrends)."""

from __future__ import annotations

from dashboard.trend_signals_ui import trend_signal_rows
from processors.trend_signals.google_trends import TRENDS_DISCLAIMER


def test_trend_signal_rows_empty_for_none_or_missing_signals():
    assert trend_signal_rows(None) == []
    assert trend_signal_rows({}) == []
    assert trend_signal_rows({"signals": []}) == []


def test_trend_signal_rows_formats_direction_and_suggestion():
    trends = {
        "disclaimer": TRENDS_DISCLAIMER,
        "keywords": ["shipping", "AI agents"],
        "signals": [
            {
                "keyword": "shipping",
                "direction": "rising",
                "recent_avg": 72.4,
                "prior_avg": 40.0,
                "corpus_alignment": "aligned",
            },
            {
                "keyword": "AI agents",
                "direction": "falling",
                "recent_avg": 10.0,
                "prior_avg": 30.0,
                "corpus_alignment": "unknown",
            },
            {
                "keyword": "niche",
                "direction": "insufficient_data",
                "recent_avg": None,
                "prior_avg": None,
            },
        ],
    }
    rows = trend_signal_rows(trends)
    assert len(rows) == 3
    assert rows[0]["keyword"] == "shipping"
    assert rows[0]["direction"] == "rising"
    assert rows[0]["recent_avg"] == 72.4
    assert "Timely" in rows[0]["suggestion"]
    assert "Cooling" in rows[1]["suggestion"]
    assert "Not enough" in rows[2]["suggestion"]
