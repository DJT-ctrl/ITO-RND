"""Canonical schema for a fully-normalized LinkedIn post record.

Why this file exists
---------------------
Every post that leaves the batch pipeline (``processors/run_pipeline.py``)
is validated against ``NormalizedPost`` before it is persisted to
``data/processed/``. This is the single source of truth for "what does a
clean, unified post record look like" — the exact deliverable Erdal's plan
asks for in T1.2 ("clean, unified schema JSON lines output ready for the
embedding engine").

If a field is renamed/added upstream (Stage 1 in ``post_analyser.py``, the
batch benchmark in ``benchmark.py``, or Stage 2's Gemini tags) and this file
isn't updated to match, validation fails loudly with a clear error instead
of silently writing a malformed row into the dataset that T1.3's embedding
step will later depend on.

Field groups (in the order they're produced by the pipeline):
  1. Identity / join keys   — from the raw scrape, untouched
  2. Raw engagement counts  — Stage 1 (processors/post_analyser.py)
  3. Content shape          — Stage 1 (processors/post_analyser.py)
  4. Timing                 — Stage 1 (processors/post_analyser.py)
  5. Engagement benchmark   — batch step (processors/benchmark.py)
  6. Qualitative tags       — Stage 2 (processors/post_analyser.py, Gemini)
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Kept in sync with the constants in processors/post_analyser.py on purpose —
# if Gemini's allowed labels change, this schema must change with them.
HookType = Literal["question", "bold_statement", "story", "list", "announcement", "other"]
Tone = Literal["professional", "casual", "emotional", "humorous", "urgent"]


class NormalizedPost(BaseModel):
    """One row of the consolidated, embedding-ready dataset.

    ``extra="forbid"`` is deliberate: it turns "someone added a new feature
    upstream but forgot to add it here" into a hard validation error at
    pipeline-run time, rather than a silently inconsistent dataset.
    """

    model_config = ConfigDict(extra="forbid")

    # ── 1. Identity / join keys ────────────────────────────────────────────
    post_id: str
    author_public_id: str = ""
    linkedin_url: str = ""

    # ── 2. Raw engagement counts (Stage 1) ─────────────────────────────────
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    shares: int = Field(ge=0)
    total_engagement: int = Field(ge=0)
    comment_ratio: Optional[float] = None
    share_ratio: Optional[float] = None

    # ── 3. Content shape (Stage 1) ─────────────────────────────────────────
    word_count: int = Field(ge=0)
    char_count: int = Field(ge=0)
    hashtag_count: int = Field(ge=0)
    emoji_count: int = Field(ge=0)
    has_media: bool
    is_job_post: bool

    # ── 4. Timing (Stage 1) ─────────────────────────────────────────────────
    # Local time when the optional profile-enrichment path resolved the
    # author's timezone (processors/post_timing.py); UTC otherwise — the
    # default (non-enriched) pipeline path always gets UTC, same as before
    # this feature existed.
    hour_of_day: Optional[int] = Field(default=None, ge=0, le=23)
    day_of_week: Optional[str] = None

    # ── 5. Engagement benchmark (batch step, processors/benchmark.py) ──────
    # Percentile/z-score are always populated by the batch pipeline.
    # engagement_rate/follower_count/audience_adjusted_* are all reserved
    # for the OPTIONAL profile-enrichment path (run_pipeline.py's
    # --with-profile-enrichment) — None whenever that flag wasn't used, or
    # a particular author's follower count wasn't resolved (partial
    # coverage is expected, not an error — see processors/benchmark.py's
    # add_audience_adjusted_benchmark).
    engagement_percentile: float = Field(ge=0, le=100)
    engagement_zscore: float
    engagement_rate: Optional[float] = None
    follower_count: Optional[int] = Field(default=None, ge=0)
    author_location_text: Optional[str] = None
    author_timezone: Optional[str] = None
    audience_adjusted_percentile: Optional[float] = Field(default=None, ge=0, le=100)
    audience_adjusted_zscore: Optional[float] = None

    # ── 6. Qualitative tags (Stage 2 — Gemini, optional) ────────────────────
    # None whenever the batch was run with --with-gemini omitted, or Gemini
    # returned a bad response for that post (see PostAnalyser.compute_gemini_features).
    hook_type: Optional[HookType] = None
    tone: Optional[Tone] = None
    topic: Optional[str] = None
    has_explicit_cta: Optional[bool] = None
    writing_style: Optional[str] = None

    # ── 7. Anomaly detection (batch step, processors/benchmark.py) ─────────
    # Flags statistically implausible engagement ratios (e.g. bot/engagement-
    # pod pollution) so processors/run_pipeline.py can route the post to a
    # separate review file instead of the main dataset. See
    # flag_engagement_anomalies() for the detection logic.
    engagement_anomaly_flag: bool = False
    anomaly_reasons: list[str] = Field(default_factory=list)
