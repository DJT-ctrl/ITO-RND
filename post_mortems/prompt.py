"""Prompt construction for A1 post-mortem generation."""

from __future__ import annotations

from agents.prompt_safety import PROMPT_DATA_PREAMBLE, wrap_untrusted_text
from post_mortems.schemas import AnomalyPostRow, VERDICTS


def build_evidence(row: AnomalyPostRow) -> dict:
    return {
        "likes": row.likes,
        "comments": row.comments,
        "shares": row.shares,
        "total_engagement": row.total_engagement,
        "comment_ratio": row.comment_ratio,
        "share_ratio": row.share_ratio,
        "engagement_percentile": row.engagement_percentile,
        "topic": row.topic,
        "hook_type": row.hook_type,
        "machine_reasons": list(row.anomaly_reasons),
    }


def build_post_mortem_prompt(row: AnomalyPostRow) -> str:
    evidence = build_evidence(row)
    reasons = ", ".join(row.anomaly_reasons) or "(none)"
    content_block = wrap_untrusted_text(row.content, tag="post_content")
    verdicts = ", ".join(VERDICTS)
    return f"""{PROMPT_DATA_PREAMBLE}

You write a short post-mortem for a LinkedIn post already flagged by a
statistical engagement-ratio anomaly detector (modified z-score on
comment_ratio and/or share_ratio vs its finalize batch; threshold 3.5).

Your job is to explain the flag using ONLY the provided numbers and text.
Do not invent new statistical rules. If the numbers do not clearly support
a bot/pod story, use verdict "ambiguous" or "data_quality".

Allowed verdicts: {verdicts}

Machine reasons: {reasons}

Evidence (JSON-like):
- likes={evidence["likes"]}
- comments={evidence["comments"]}
- shares={evidence["shares"]}
- total_engagement={evidence["total_engagement"]}
- comment_ratio={evidence["comment_ratio"]}
- share_ratio={evidence["share_ratio"]}
- engagement_percentile={evidence["engagement_percentile"]}
- topic={evidence["topic"]}
- hook_type={evidence["hook_type"]}

{content_block}

Return:
- verdict: one of the allowed values
- summary: 2-4 sentences grounded in the evidence
- lesson_for_models: one line on what NOT to learn from this post as a
  success/failure pattern
"""
