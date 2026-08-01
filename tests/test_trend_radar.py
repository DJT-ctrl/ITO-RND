"""Unit tests for A2 trend radar clustering math (no DB / Gemini)."""

from __future__ import annotations

from datetime import date

import numpy as np
from pydantic_ai.models.test import TestModel

from trend_radar.clustering import (
    choose_k,
    cluster_posts,
    cosine_distance,
    match_clusters_to_previous,
    monday_on_or_before,
    week_window,
)
from trend_radar.labels import label_cluster
from trend_radar.schemas import ClusterSnapshot, CorpusPostVector


def _vec(seed: int, dim: int = 32) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim)
    return v / (np.linalg.norm(v) + 1e-12)


def test_monday_on_or_before():
    assert monday_on_or_before(date(2026, 7, 23)) == date(2026, 7, 20)  # Thu -> Mon


def test_week_window_is_seven_days():
    start, end, prev_start, prev_end = week_window(date(2026, 7, 20))
    assert (end - start).days == 7
    assert prev_end == start
    assert (prev_end - prev_start).days == 7


def test_choose_k_bounds():
    assert choose_k(3) == 0
    assert choose_k(200) == 5  # 200 // 40
    assert choose_k(5000) == 32


def test_cluster_posts_and_growth_match():
    # Two tight groups in 32-d space, enough posts for min size.
    posts: list[CorpusPostVector] = []
    for i in range(20):
        base = _vec(1 if i < 10 else 2)
        noise = np.random.default_rng(100 + i).normal(scale=0.01, size=base.shape)
        emb = base + noise
        emb = emb / (np.linalg.norm(emb) + 1e-12)
        posts.append(
            CorpusPostVector(
                post_id=f"p{i}",
                embedding=emb,
                total_engagement=10 + i,
                topic="alpha" if i < 10 else "beta",
                content=f"post {i} about {'alpha' if i < 10 else 'beta'}",
            )
        )
    # Force enough volume for k>=4 path by duplicating groups
    extra = []
    for i in range(20, 80):
        base = _vec(1 if i % 2 == 0 else 2)
        noise = np.random.default_rng(200 + i).normal(scale=0.02, size=base.shape)
        emb = base + noise
        emb = emb / (np.linalg.norm(emb) + 1e-12)
        extra.append(
            CorpusPostVector(
                post_id=f"p{i}",
                embedding=emb,
                total_engagement=i,
                topic="alpha" if i % 2 == 0 else "beta",
                content=f"post {i}",
            )
        )
    snaps = cluster_posts(posts + extra, random_state=0)
    assert snaps
    assert all(s.post_count >= 5 for s in snaps)

    previous = [(s.cluster_id, s.centroid, s.post_count) for s in snaps]
    # Simulate growth: same centroids, inflated counts by reclustering same data
    grown = match_clusters_to_previous(snaps, previous)
    assert len(grown) == len(snaps)
    # Perfect match → growth_rate ~ 0
    assert all(g.growth_rate is not None for g in grown)
    assert all(abs(g.growth_rate or 0) < 1e-9 for g in grown)


def test_cosine_distance_identical_is_zero():
    v = _vec(7)
    assert cosine_distance(v, v) < 1e-9


def test_label_cluster_with_test_model():
    snap = ClusterSnapshot(
        cluster_id="c_test",
        label="",
        post_count=10,
        share_of_corpus=0.1,
        growth_rate=0.2,
        mean_total_engagement=12.0,
        example_post_ids=["a"],
        centroid=_vec(3),
        example_snippets=["Shipping AI agents to production safely."],
        topic_hints=["AI"],
    )
    model = TestModel(custom_output_args={"label": "AI shipping"})
    assert label_cluster(snap, model=model) == "AI shipping"
