"""Tests for feedback store dashboard helpers."""

from unittest.mock import MagicMock

from feedback.store import count_feedback_coverage, list_clusters, list_recent_feedback


def test_count_feedback_coverage():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (10, 7)

    coverage = count_feedback_coverage(conn)
    assert coverage == {
        "validated": 10,
        "with_feedback": 7,
        "missing_feedback": 3,
    }


def test_list_clusters():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [
        ("short_prose_micro", "short prose posts (micro followers)", 12, -4.5, 2.1),
    ]

    clusters = list_clusters(conn)
    assert len(clusters) == 1
    assert clusters[0].cluster_id == "short_prose_micro"
    assert clusters[0].sample_count == 12
    assert clusters[0].mean_delta == -4.5


def test_list_recent_feedback_empty():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = []

    assert list_recent_feedback(conn) == []
