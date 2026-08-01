"""Per-user niche profiles derived from tagged posts (T10.6)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

import psycopg

from phase_10.topics import DEFAULT_NICHE, is_valid_niche, normalize_topic_to_niche


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def compute_user_niche_rows(
    post_rows: Iterable[tuple[str, str | None]],
) -> list[tuple[str, str, int, float]]:
    """Build ``(user_id, niche, post_count, weight)`` from ``(user_id, niche)`` posts.

    Per-user ``weight`` is that niche's share of the user's tagged posts.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for user_id, niche_raw in post_rows:
        if not user_id:
            continue
        niche = niche_raw if is_valid_niche(niche_raw) else normalize_topic_to_niche(niche_raw)
        if not is_valid_niche(niche):
            niche = DEFAULT_NICHE
        counts[user_id][niche] += 1

    rows: list[tuple[str, str, int, float]] = []
    for user_id, niche_counts in counts.items():
        total = sum(niche_counts.values())
        if total <= 0:
            continue
        for niche, post_count in niche_counts.items():
            rows.append((user_id, niche, post_count, round(post_count / total, 6)))
    return rows


def primary_niche_by_user(
    user_niche_rows: Iterable[tuple[str, str, int, float]],
) -> dict[str, str]:
    """Map each user to their primary niche (argmax post_count; tie → name sort)."""
    best: dict[str, tuple[int, str]] = {}
    for user_id, niche, post_count, _weight in user_niche_rows:
        current = best.get(user_id)
        if current is None or post_count > current[0] or (
            post_count == current[0] and niche < current[1]
        ):
            best[user_id] = (post_count, niche)
    return {user_id: niche for user_id, (_count, niche) in best.items()}


def global_weights_from_primaries(primary_by_user: dict[str, str]) -> dict[str, float]:
    """Share of users whose primary niche is N; omit niches with zero users."""
    if not primary_by_user:
        return {}
    tallies: dict[str, int] = defaultdict(int)
    for niche in primary_by_user.values():
        tallies[niche] += 1
    total = len(primary_by_user)
    return {
        niche: round(count / total, 6)
        for niche, count in sorted(tallies.items())
        if count > 0
    }


def refresh_user_niches(conn: psycopg.Connection) -> dict[str, float]:
    """Recompute ``user_niches`` from posts and return global plan weights."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, niche
            FROM posts
            WHERE user_id IS NOT NULL
              AND BTRIM(user_id) <> ''
              AND niche IS NOT NULL
              AND BTRIM(niche) <> ''
            """
        )
        post_rows = cur.fetchall()
        niche_rows = compute_user_niche_rows(post_rows)
        now = _utc_now()

        cur.execute("DELETE FROM user_niches")
        if niche_rows:
            cur.executemany(
                """
                INSERT INTO user_niches (user_id, niche, post_count, weight, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [(user_id, niche, count, weight, now) for user_id, niche, count, weight in niche_rows],
            )
        conn.commit()

    primaries = primary_niche_by_user(niche_rows)
    return global_weights_from_primaries(primaries)
