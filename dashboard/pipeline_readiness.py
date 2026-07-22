"""Data-aware readiness for corpus / validation pipeline step strips.

Read-only: inspects raw files, pipeline bundles, and (when available)
prediction counts. No writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from config.paths import resolve_data_path
from config.settings import Settings, load_settings
from storage.pipeline_registry import list_bundles

StepState = Literal["done", "current", "ready", "blocked", "optional"]
CorpusStep = Literal["collect", "analyse", "patterns", "embed", "search"]
ValidationStep = Literal["predict", "queue", "accuracy", "feedback"]


@dataclass
class StepReadiness:
    """Per-step chip state plus a short caption fragment."""

    state: StepState
    count: int = 0
    hint: str = ""


@dataclass
class PipelineReadiness:
    """Full strip payload for corpus or validation."""

    kind: Literal["corpus", "validation"]
    steps: dict[str, StepReadiness] = field(default_factory=dict)
    caption: str = ""


def _raw_collection_paths(settings: Settings) -> list[Path]:
    data_dir = resolve_data_path(settings.raw_data_dir)
    if not data_dir.exists():
        return []
    return sorted(
        (p for p in data_dir.glob("linkedin_*.json") if "profiles" not in p.name),
        reverse=True,
    )


def _postgres_post_count(settings: Settings) -> int:
    if not settings.database_url:
        return 0
    try:
        from pgvector.psycopg import register_vector

        from storage.vector_store import get_connection

        conn = get_connection(settings)
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM posts")
                row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _prediction_status_counts(settings: Settings) -> dict[str, int]:
    if not settings.database_url:
        return {}
    try:
        from storage.vector_store import create_schema, get_connection

        conn = get_connection(settings)
        try:
            create_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*)::INTEGER
                    FROM predictions
                    GROUP BY status
                    """
                )
                return {str(row[0]): int(row[1]) for row in cur.fetchall()}
        finally:
            conn.close()
    except Exception:
        return {}


def _vectorized_ready_count(settings: Settings) -> int:
    try:
        from validation_pipeline.vectorized_corpus import (
            discover_vectorized_datasets,
            load_all_vectorized_collected_posts,
        )

        datasets = discover_vectorized_datasets(settings)
        if not datasets:
            return 0
        posts, _ = load_all_vectorized_collected_posts(settings)
        return len(posts)
    except Exception:
        return 0


def compute_corpus_readiness(
    current: CorpusStep,
    *,
    settings: Settings | None = None,
) -> PipelineReadiness:
    """Derive done / ready / blocked / optional states for corpus steps 1–5."""
    settings = settings or load_settings()
    raw = _raw_collection_paths(settings)
    raw_n = len(raw)
    analysed = list_bundles(min_stage="analysed")
    gemini = list_bundles(min_stage="analysed", require_gemini=True)
    embedded = list_bundles(min_stage="embedded")
    ingested = list_bundles(min_stage="ingested")
    analysed_only = [b for b in analysed if not b.embeddings_npy]
    pg_posts = _postgres_post_count(settings)

    steps: dict[str, StepReadiness] = {}

    # Collect: done if any raw files; otherwise blocked until scrape.
    if raw_n:
        steps["collect"] = StepReadiness("done", raw_n, f"{raw_n} collection(s)")
    else:
        steps["collect"] = StepReadiness("ready" if current == "collect" else "blocked", 0, "no scrapes yet")

    # Analyse: done if analysed bundles; ready if raw exists; else blocked.
    if analysed:
        steps["analyse"] = StepReadiness("done", len(analysed), f"{len(analysed)} analysed")
    elif raw_n:
        steps["analyse"] = StepReadiness("ready", raw_n, f"{raw_n} → Analyse")
    else:
        steps["analyse"] = StepReadiness("blocked", 0, "need Collect first")

    # Patterns: optional — done if Gemini analysed; never blocks Embed.
    if gemini:
        steps["patterns"] = StepReadiness("done", len(gemini), f"{len(gemini)} with Gemini")
    elif analysed:
        steps["patterns"] = StepReadiness("optional", len(analysed), "optional · skip OK")
    else:
        steps["patterns"] = StepReadiness("optional", 0, "optional")

    # Embed: done if embeddings; ready if analysed without embeddings.
    if embedded:
        steps["embed"] = StepReadiness("done", len(embedded), f"{len(embedded)} embedded")
    elif analysed:
        steps["embed"] = StepReadiness(
            "ready",
            len(analysed_only) or len(analysed),
            f"{len(analysed_only) or len(analysed)} → Embed",
        )
    else:
        steps["embed"] = StepReadiness("blocked", 0, "need Analyse first")

    # Search: done/ready if ingested or Postgres posts; else blocked (needs ingest).
    if ingested or pg_posts:
        n = len(ingested) if ingested else pg_posts
        steps["search"] = StepReadiness(
            "done",
            n,
            f"{pg_posts} posts in DB" if pg_posts else f"{len(ingested)} ingested",
        )
    elif embedded:
        steps["search"] = StepReadiness("ready", len(embedded), "Embed done · needs ingest")
    else:
        steps["search"] = StepReadiness("blocked", 0, "need Embed + ingest")

    # Mark current page (overrides done/ready styling in the strip renderer).
    if current in steps:
        # Keep underlying data, but strip uses "current" for the active chip.
        pass

    caption_parts: list[str] = []
    order: list[CorpusStep] = ["collect", "analyse", "patterns", "embed", "search"]
    try:
        current_idx = order.index(current)  # type: ignore[arg-type]
    except ValueError:
        current_idx = 0
    # Forward-looking ready cues only (avoid "need X first" while already on X).
    for key in order[current_idx + 1 :]:
        info = steps[key]
        if info.state == "ready" and info.hint:
            caption_parts.append(info.hint)
            break
    if not caption_parts and current == "embed" and embedded and not (ingested or pg_posts):
        caption_parts.append("Embed done · Search needs ingest")
    if not caption_parts and analysed_only and current in ("analyse", "patterns"):
        caption_parts.append(f"{len(analysed_only)} analysed → Embed")
    # Upstream data waiting to be consumed on an earlier step.
    if not caption_parts:
        for key in order[:current_idx]:
            info = steps[key]
            if info.state == "ready" and info.hint:
                caption_parts.append(info.hint)
                break

    return PipelineReadiness(kind="corpus", steps=steps, caption=" · ".join(caption_parts))


def compute_validation_readiness(
    current: ValidationStep,
    *,
    settings: Settings | None = None,
) -> PipelineReadiness:
    """Derive done / ready / blocked states for validation steps 1–4."""
    settings = settings or load_settings()
    status_counts = _prediction_status_counts(settings)
    scheduled = int(status_counts.get("scheduled", 0))
    validated = int(status_counts.get("validated", 0))
    failed = int(status_counts.get("failed", 0))
    total_pred = sum(status_counts.values())
    vectorized_n = _vectorized_ready_count(settings)
    raw_n = len(_raw_collection_paths(settings))

    steps: dict[str, StepReadiness] = {}

    if total_pred:
        steps["predict"] = StepReadiness("done", total_pred, f"{total_pred} prediction(s)")
    elif vectorized_n or raw_n:
        steps["predict"] = StepReadiness(
            "ready",
            vectorized_n or raw_n,
            f"{vectorized_n or raw_n} posts ready to predict",
        )
    else:
        steps["predict"] = StepReadiness("blocked", 0, "need corpus or scrape first")

    if scheduled:
        steps["queue"] = StepReadiness("ready", scheduled, f"{scheduled} scheduled")
    elif validated or failed:
        steps["queue"] = StepReadiness("done", validated + failed, "queue clear")
    elif total_pred:
        steps["queue"] = StepReadiness("ready", 0, "open Queue")
    else:
        steps["queue"] = StepReadiness("blocked", 0, "need Predict first")

    if validated:
        steps["accuracy"] = StepReadiness("done", validated, f"{validated} graded")
    elif scheduled:
        steps["accuracy"] = StepReadiness("blocked", 0, "grade in Queue first")
    else:
        steps["accuracy"] = StepReadiness("blocked", 0, "no graded rows yet")

    if validated:
        steps["feedback"] = StepReadiness("ready", validated, f"{validated} → Feedback")
    else:
        steps["feedback"] = StepReadiness("blocked", 0, "need graded predictions")

    caption_parts: list[str] = []
    if current == "predict" and scheduled:
        caption_parts.append(f"{scheduled} scheduled → Queue")
    elif current == "queue" and validated:
        caption_parts.append(f"{validated} graded → Accuracy / Feedback")
    elif current in ("accuracy", "feedback") and scheduled:
        caption_parts.append(f"{scheduled} still scheduled")
    elif steps.get("predict", StepReadiness("blocked")).state == "ready":
        caption_parts.append(steps["predict"].hint)

    return PipelineReadiness(
        kind="validation",
        steps=steps,
        caption=" · ".join(caption_parts),
    )


def compute_readiness(
    kind: Literal["corpus", "validation"],
    current: str,
    *,
    settings: Settings | None = None,
) -> PipelineReadiness:
    if kind == "corpus":
        return compute_corpus_readiness(current, settings=settings)  # type: ignore[arg-type]
    return compute_validation_readiness(current, settings=settings)  # type: ignore[arg-type]
