"""Import corpus posts into the validation pipeline for backtesting."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from config.paths import resolve_data_path
from config.settings import Settings, load_settings
from storage.vector_store import create_schema, get_connection
from validation_pipeline.predict import predict_for_post, save_prediction
from validation_pipeline.schemas import CollectedPost, PredictionRecord
from validation_pipeline.store import prediction_exists


class CorpusImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    predictions: list[PredictionRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _parse_posted_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def corpus_row_to_collected(row: dict[str, Any]) -> Optional[CollectedPost]:
    post_id = str(row.get("post_id") or row.get("id") or "").strip()
    linkedin_url = str(row.get("linkedin_url") or row.get("linkedinUrl") or "").strip()
    content = str(row.get("content") or "").strip()
    if not post_id or not linkedin_url or not content:
        return None

    likes = int(row.get("likes") or row.get("baseline_likes") or 0)
    comments = int(row.get("comments") or row.get("baseline_comments") or 0)
    shares = int(row.get("shares") or row.get("baseline_shares") or 0)
    total = row.get("total_engagement")
    if total is None:
        total = likes + comments + shares

    posted_raw = row.get("posted_at") or row.get("postedAt")
    if isinstance(posted_raw, dict):
        posted_raw = posted_raw.get("timestamp") or posted_raw.get("date")

    return CollectedPost(
        linkedin_post_id=post_id,
        linkedin_url=linkedin_url,
        author_public_id=str(row.get("author_public_id") or row.get("authorPublicId") or ""),
        content=content,
        posted_at=_parse_posted_at(posted_raw),
        follower_count=row.get("follower_count"),
        likes=likes,
        comments=comments,
        shares=shares,
        total_engagement=int(total),
    )


def load_corpus_posts_from_db(
    settings: Settings,
    *,
    limit: int = 100,
    search: str = "",
) -> list[dict[str, Any]]:
    """Load posts from the vector DB corpus for validation import."""
    if not settings.database_url:
        return []
    conn = get_connection(settings)
    try:
        create_schema(conn)
        sql = """
            SELECT post_id, linkedin_url, author_public_id, content,
                   likes, comments, shares, total_engagement,
                   follower_count, engagement_percentile, inserted_at
            FROM posts
            WHERE engagement_anomaly_flag = FALSE
        """
        params: list[Any] = []
        if search.strip():
            sql += " AND (content ILIKE %s OR post_id ILIKE %s OR linkedin_url ILIKE %s)"
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY inserted_at DESC LIMIT %s"
        params.append(limit)
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            columns = [col.name for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def load_corpus_posts_from_file(path: Path) -> list[dict[str, Any]]:
    """Load posts from a JSON/JSONL/CSV artifact produced by the corpus pipeline."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("posts"), list):
        return data["posts"]
    raise ValueError(f"Unsupported file format: {path}")


def list_corpus_artifact_files(settings: Settings) -> list[Path]:
    """Recent processed/validation JSON artifacts suitable for import."""
    roots = [
        resolve_data_path("data/processed"),
        resolve_data_path(settings.validation_data_dir),
        resolve_data_path(settings.raw_data_dir),
    ]
    patterns = ("*.json", "*.jsonl", "*.csv")
    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.glob(pattern):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:40]


async def import_corpus_posts_async(
    posts: list[CollectedPost],
    settings: Settings,
    *,
    due_immediately: bool = True,
    skip_existing: bool = True,
) -> CorpusImportResult:
    """Schedule predictions for corpus posts (optionally due immediately for testing)."""
    result = CorpusImportResult()
    due_at = datetime.now(timezone.utc) if due_immediately else None

    for post in posts:
        if skip_existing:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                if prediction_exists(conn, post.linkedin_post_id):
                    result.skipped += 1
                    continue
            finally:
                conn.close()

        try:
            prediction = await predict_for_post(post, settings)
            saved = save_prediction(
                post,
                prediction,
                settings,
                validation_due_at=due_at,
            )
            if saved is None:
                result.skipped += 1
            else:
                result.imported += 1
                result.predictions.append(saved)
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")

    return result


def import_corpus_posts(
    posts: list[CollectedPost],
    settings: Settings | None = None,
    **kwargs: Any,
) -> CorpusImportResult:
    settings = settings or load_settings()
    return asyncio.run(import_corpus_posts_async(posts, settings, **kwargs))
