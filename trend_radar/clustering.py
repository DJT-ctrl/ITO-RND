"""Deterministic clustering + week-over-week matching for A2."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import normalize

from trend_radar.schemas import ClusterSnapshot, CorpusPostVector

MATCH_COSINE_MAX_DISTANCE = 0.35
MIN_CLUSTER_SIZE = 5
DEFAULT_RANDOM_STATE = 0


def monday_on_or_before(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_window(
    week_start: date,
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (this_start, this_end, prev_start, prev_end) as UTC datetimes."""
    this_start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    this_end = this_start + timedelta(days=7)
    prev_start = this_start - timedelta(days=7)
    prev_end = this_start
    return this_start, this_end, prev_start, prev_end


def choose_k(n_posts: int) -> int:
    if n_posts < MIN_CLUSTER_SIZE:
        return 0
    return int(min(32, max(4, n_posts // 40)))


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    return normalize(matrix, norm="l2", axis=1)


def _new_cluster_id(centroid: np.ndarray) -> str:
    digest = hashlib.sha1(centroid.astype(np.float64).tobytes()).hexdigest()[:10]
    return f"c_{digest}"


def cluster_posts(
    posts: Sequence[CorpusPostVector],
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> list[ClusterSnapshot]:
    """MiniBatchKMeans on L2-normalized embeddings; drop tiny clusters."""
    n = len(posts)
    k = choose_k(n)
    if k == 0:
        return []

    matrix = np.vstack([p.embedding for p in posts]).astype(np.float64)
    matrix = _l2_normalize(matrix)
    model = MiniBatchKMeans(
        n_clusters=k,
        random_state=random_state,
        n_init=3,
        batch_size=min(1024, max(k * 10, n)),
    )
    labels = model.fit_predict(matrix)
    snapshots: list[ClusterSnapshot] = []
    for local_id in range(k):
        indexes = np.where(labels == local_id)[0]
        if len(indexes) < MIN_CLUSTER_SIZE:
            continue
        members = [posts[i] for i in indexes]
        centroid = _l2_normalize(model.cluster_centers_[local_id].reshape(1, -1))[0]
        engagements = [m.total_engagement for m in members]
        # Prefer mid-engagement examples for labeling.
        ranked = sorted(members, key=lambda m: m.total_engagement)
        mid = len(ranked) // 2
        examples = ranked[max(0, mid - 1) : mid + 2][:3]
        if not examples:
            examples = ranked[:3]
        topic_hints = [m.topic for m in members if m.topic]
        snapshots.append(
            ClusterSnapshot(
                cluster_id=_new_cluster_id(centroid),
                label="",
                post_count=len(members),
                share_of_corpus=len(members) / float(n),
                growth_rate=None,
                mean_total_engagement=float(sum(engagements) / len(engagements)),
                example_post_ids=[e.post_id for e in examples],
                centroid=centroid,
                example_snippets=[(e.content or "")[:280] for e in examples],
                topic_hints=topic_hints[:5],
            )
        )
    return snapshots


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    a_n = a / (np.linalg.norm(a) + 1e-12)
    b_n = b / (np.linalg.norm(b) + 1e-12)
    return float(1.0 - np.dot(a_n, b_n))


def match_clusters_to_previous(
    current: list[ClusterSnapshot],
    previous: list[tuple[str, np.ndarray, int]],
    *,
    max_distance: float = MATCH_COSINE_MAX_DISTANCE,
) -> list[ClusterSnapshot]:
    """Assign stable cluster_ids from prior week via Hungarian matching.

    previous entries: (cluster_id, centroid, post_count)
    """
    if not current:
        return []
    if not previous:
        return current

    cost = np.zeros((len(current), len(previous)), dtype=np.float64)
    for i, snap in enumerate(current):
        for j, (_, centroid, _) in enumerate(previous):
            cost[i, j] = cosine_distance(snap.centroid, centroid)

    row_ind, col_ind = linear_sum_assignment(cost)
    assigned_prev: set[int] = set()
    matched: list[ClusterSnapshot] = []

    for i, j in zip(row_ind, col_ind):
        dist = float(cost[i, j])
        snap = current[i]
        if dist <= max_distance and j not in assigned_prev:
            prev_id, _, prev_count = previous[j]
            growth = (snap.post_count - prev_count) / float(max(prev_count, 1))
            matched.append(
                ClusterSnapshot(
                    cluster_id=prev_id,
                    label=snap.label,
                    post_count=snap.post_count,
                    share_of_corpus=snap.share_of_corpus,
                    growth_rate=growth,
                    mean_total_engagement=snap.mean_total_engagement,
                    example_post_ids=snap.example_post_ids,
                    centroid=snap.centroid,
                    example_snippets=snap.example_snippets,
                    topic_hints=snap.topic_hints,
                )
            )
            assigned_prev.add(j)
        else:
            matched.append(snap)

    # Any current clusters not in the assignment pairs (rectangular case)
    assigned_current = set(row_ind.tolist())
    for i, snap in enumerate(current):
        if i not in assigned_current:
            matched.append(snap)
    return matched


def keyword_fallback_label(snap: ClusterSnapshot) -> str:
    if snap.topic_hints:
        # majority-ish: first unique topics
        seen: list[str] = []
        for topic in snap.topic_hints:
            if topic and topic not in seen:
                seen.append(topic)
            if len(seen) >= 2:
                break
        if seen:
            return " / ".join(seen)[:80]
    return f"topic cluster {snap.cluster_id}"
