"""Phase B — finds patterns/correlations in the normalized dataset.

This is deliberately NOT another Gemini pass. Asking an LLM to "look at
these rows and find the correlation" is exactly the kind of numeric
reasoning-over-many-rows task LLMs are unreliable at, and it doesn't scale
as the dataset grows (see /memories/session/plan.md for the full
reasoning). Everything here is plain, deterministic statistics (pandas),
with an optional small ML model — both fully reproducible: run it twice on
the same data, get the same answer.

Three independent analyses, from simplest to most involved:
  group_engagement_by_tag()    — mean engagement per categorical tag
                                  (hook_type, tone, day_of_week, topic)
  correlate_numeric_features() — Pearson correlation of numeric features
                                  against the engagement benchmark
  feature_importance()         — optional: a small gradient-boosted model
                                  predicting engagement, read off for which
                                  features mattered most. Only meaningful
                                  with enough rows — see min_rows below.

Every function takes the same input: the list of validated records
produced by processors/run_pipeline.py (or read back from a saved
data/processed/*.jsonl file).
"""

from typing import Any

import pandas as pd

# Only columns that exist are ever analysed — Stage-2-only fields (hook_type,
# tone, topic) are simply skipped if the batch was run without --with-gemini.
_CATEGORICAL_TAGS = ("hook_type", "tone", "day_of_week", "topic")
_NUMERIC_FEATURES = (
    "word_count",
    "char_count",
    "hashtag_count",
    "emoji_count",
    "hour_of_day",
    "has_media",
    "is_job_post",
    "has_explicit_cta",
)
_TARGET = "engagement_zscore"


def _to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        raise ValueError("records list is empty — nothing to analyse.")
    return pd.DataFrame.from_records(records)


def group_engagement_by_tag(records: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    """Mean/median engagement grouped by each available categorical tag.

    Returns one DataFrame per tag column, keyed by tag name. A tag is
    skipped entirely if it's missing from every record (e.g. hook_type/tone
    when Stage 2 wasn't run) rather than raising, since which tags are
    available legitimately varies run to run.
    """
    df = _to_frame(records)
    results: dict[str, pd.DataFrame] = {}
    for tag in _CATEGORICAL_TAGS:
        if tag not in df.columns or df[tag].isna().all():
            continue
        grouped = (
            df.dropna(subset=[tag])
            .groupby(tag)[_TARGET]
            .agg(["mean", "median", "count"])
            .sort_values("mean", ascending=False)
        )
        results[tag] = grouped
    return results


def correlate_numeric_features(records: list[dict[str, Any]]) -> pd.Series:
    """Pearson correlation of each numeric feature against engagement.

    Returns a Series sorted from strongest positive to strongest negative
    correlation. Booleans (has_media, is_job_post, has_explicit_cta) are
    coerced to 0/1 so point-biserial correlation falls out for free.
    """
    df = _to_frame(records)
    available = [f for f in _NUMERIC_FEATURES if f in df.columns]
    if not available:
        raise ValueError("None of the expected numeric features are present in records.")
    numeric_df = df[[*available, _TARGET]].apply(pd.to_numeric, errors="coerce")
    return numeric_df.corr(numeric_only=True)[_TARGET].drop(_TARGET).sort_values(ascending=False)


def feature_importance(records: list[dict[str, Any]], min_rows: int = 50) -> pd.Series:
    """Train a small gradient-boosted regressor and return feature importances.

    Deliberately gated behind ``min_rows``: with only a handful of posts a
    model will happily overfit and report a confident-looking but
    meaningless "pattern". Below the threshold, use
    group_engagement_by_tag()/correlate_numeric_features() instead — they
    degrade gracefully with small samples, a model does not.
    """
    df = _to_frame(records)
    if len(df) < min_rows:
        raise ValueError(
            f"Need at least {min_rows} posts for a meaningful model, got {len(df)}. "
            "Use group_engagement_by_tag()/correlate_numeric_features() instead."
        )

    # Imported locally: scikit-learn is only needed for this one optional
    # function, so a missing/broken install doesn't break the rest of the module.
    from sklearn.ensemble import GradientBoostingRegressor

    available = [f for f in _NUMERIC_FEATURES if f in df.columns]
    features = df[available].apply(pd.to_numeric, errors="coerce").fillna(0)
    target = pd.to_numeric(df[_TARGET], errors="coerce").fillna(0)

    model = GradientBoostingRegressor(random_state=0)
    model.fit(features, target)
    return pd.Series(model.feature_importances_, index=available).sort_values(ascending=False)
