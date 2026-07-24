"""Deterministic cognitive-load / clarity metrics for the clarity diagnostic (T7.5).

Pre-computes reading-grade, jargon density, and mobile-scan structure from the
draft. The clarity agent treats these as facts in its prompt — same pattern as
Tier-1 discoverability for SEO. No external readability libraries.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+[\s\n]+|[.!?]+$")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_BULLET_RE = re.compile(r"^([-*•]|\d+[.)])\s+")
_HASHTAG_MENTION_RE = re.compile(r"[@#]\w+")

# Short function words / LinkedIn glue — never count as jargon.
_COMMON_WORDS = frozenset(
    """
    a an the and or but if then else when while for of to in on at by from with
    as is are was were be been being have has had do does did will would can
    could should may might must this that these those it its we our you your
    they their them he she his her i me my not no yes so than too very just
    also more most much many some any all each other into over after before
    about up out off than about like get got make made work team post share
    comment like new today here what how why who where which
    """.split()
)

# LinkedIn-ish platitude / corporate-ish tokens that inflate cognitive load.
_JARGON_LEXICON = frozenset(
    """
    synergy leverage utilize utilise paradigm ecosystem scalable actionable
    bandwidth deliverables stakeholders unlock empower transformative holistic
    disrupt disruption innovative innovation operationalize operationalise
    ideate ideating alignment align kpi okr roi roi's deepdive deep-dive
    circleback circle-back lowhanging low-hanging valueadd value-add
    nextgen next-generation bestinclass best-in-class goforward go-forward
    """.split()
)


def count_syllables(word: str) -> int:
    """Approximate English syllable count (vowel-group heuristic)."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if w.endswith("e") and len(w) > 2 and w[-2] != "l":
        w = w[:-1]
    groups = re.findall(r"[aeiouy]+", w)
    return max(1, len(groups))


def _content_words(draft: str) -> list[str]:
    cleaned = _HASHTAG_MENTION_RE.sub(" ", draft or "")
    return [m.group(0).lower() for m in _WORD_RE.finditer(cleaned)]


def _sentences(draft: str) -> list[str]:
    text = (draft or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


def _paragraphs(draft: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", draft or "") if b.strip()]
    if blocks:
        return blocks
    text = (draft or "").strip()
    return [text] if text else []


def flesch_kincaid_grade(words: list[str], sentence_count: int) -> Optional[float]:
    """Flesch–Kincaid grade level; None when the draft is too short to score."""
    if len(words) < 5 or sentence_count < 1:
        return None
    syllables = sum(count_syllables(w) for w in words)
    grade = (
        0.39 * (len(words) / sentence_count)
        + 11.8 * (syllables / len(words))
        - 15.59
    )
    return round(max(0.0, grade), 1)


def jargon_density_percent(words: list[str]) -> float:
    """Share of content words that look like jargon (0–100)."""
    if not words:
        return 0.0
    jargon = 0
    for w in words:
        if w in _COMMON_WORDS:
            continue
        if w in _JARGON_LEXICON:
            jargon += 1
            continue
        # Long / multi-syllable content words tend to raise mobile cognitive load.
        if len(w) >= 12 or count_syllables(w) >= 4:
            jargon += 1
    return round(100.0 * jargon / len(words), 1)


def compute_clarity_metrics(draft: str) -> dict[str, Any]:
    """Return reproducible clarity / cognitive-load metrics for a draft."""
    text = draft or ""
    words = _content_words(text)
    sentences = _sentences(text)
    paragraphs = _paragraphs(text)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    bullet_lines = sum(1 for ln in lines if _BULLET_RE.match(ln.strip()))
    line_break_count = max(0, len(lines) - 1) if lines else 0

    para_word_counts = [len(_content_words(p)) for p in paragraphs]
    max_paragraph_words = max(para_word_counts) if para_word_counts else 0
    avg_words_per_sentence = (
        round(len(words) / len(sentences), 1) if sentences and words else 0.0
    )
    fk = flesch_kincaid_grade(words, len(sentences) if sentences else 1)
    jargon_pct = jargon_density_percent(words)

    wall_of_text = bool(
        max_paragraph_words >= 80
        or (
            len(paragraphs) <= 1
            and len(words) >= 60
            and bullet_lines == 0
            and line_break_count < 3
        )
    )
    sparse_breaks = bool(len(words) >= 80 and line_break_count < 4 and bullet_lines == 0)

    signals: list[dict[str, Any]] = []

    if fk is None:
        signals.append(
            {
                "check": "flesch_kincaid_grade",
                "value": None,
                "status": "warn",
                "note": "Draft too short for a reliable reading-grade estimate.",
            }
        )
    elif fk <= 10:
        signals.append(
            {
                "check": "flesch_kincaid_grade",
                "value": fk,
                "status": "pass",
                "note": f"Reading grade ~{fk} — generally mobile-friendly.",
            }
        )
    elif fk <= 14:
        signals.append(
            {
                "check": "flesch_kincaid_grade",
                "value": fk,
                "status": "warn",
                "note": f"Reading grade ~{fk} — a bit heavy for quick LinkedIn scanning.",
            }
        )
    else:
        signals.append(
            {
                "check": "flesch_kincaid_grade",
                "value": fk,
                "status": "fail",
                "note": f"Reading grade ~{fk} — likely too dense for mobile skim.",
            }
        )

    if jargon_pct <= 8:
        j_status, j_note = "pass", f"Jargon density {jargon_pct}% — mostly plain language."
    elif jargon_pct <= 15:
        j_status, j_note = "warn", f"Jargon density {jargon_pct}% — trim a few heavy terms."
    else:
        j_status, j_note = "fail", f"Jargon density {jargon_pct}% — high cognitive load."
    signals.append(
        {
            "check": "jargon_density_percent",
            "value": jargon_pct,
            "status": j_status,
            "note": j_note,
        }
    )

    if wall_of_text:
        signals.append(
            {
                "check": "wall_of_text",
                "value": max_paragraph_words,
                "status": "fail",
                "note": (
                    f"Dense block detected (longest paragraph ~{max_paragraph_words} words). "
                    "Break into shorter lines/paragraphs for mobile."
                ),
            }
        )
    elif sparse_breaks:
        signals.append(
            {
                "check": "wall_of_text",
                "value": max_paragraph_words,
                "status": "warn",
                "note": "Long post with few line breaks — add short paragraphs or bullets.",
            }
        )
    else:
        signals.append(
            {
                "check": "wall_of_text",
                "value": max_paragraph_words,
                "status": "pass",
                "note": "Structure looks scannable (paragraphs / breaks / bullets).",
            }
        )

    if bullet_lines >= 2:
        signals.append(
            {
                "check": "mobile_scan",
                "value": bullet_lines,
                "status": "pass",
                "note": f"{bullet_lines} list-like lines help mobile scanning.",
            }
        )
    elif line_break_count >= 3 or len(paragraphs) >= 2:
        signals.append(
            {
                "check": "mobile_scan",
                "value": line_break_count,
                "status": "pass",
                "note": "Multiple line breaks / paragraphs support mobile skim.",
            }
        )
    elif len(words) < 40:
        signals.append(
            {
                "check": "mobile_scan",
                "value": line_break_count,
                "status": "pass",
                "note": "Short draft — scan structure is less critical.",
            }
        )
    else:
        signals.append(
            {
                "check": "mobile_scan",
                "value": line_break_count,
                "status": "warn",
                "note": "Few visual breaks — consider short paragraphs or bullets.",
            }
        )

    status_weights = {"pass": 10.0, "warn": 6.0, "fail": 2.0}
    scores = [status_weights.get(s["status"], 6.0) for s in signals]
    deterministic_score = round(sum(scores) / len(scores), 1) if scores else 5.0

    return {
        "word_count": len(words),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "avg_words_per_sentence": avg_words_per_sentence,
        "flesch_kincaid_grade": fk,
        "jargon_density_percent": jargon_pct,
        "max_paragraph_words": max_paragraph_words,
        "line_break_count": line_break_count,
        "bullet_line_count": bullet_lines,
        "wall_of_text": wall_of_text,
        "signals": signals,
        "deterministic_score": deterministic_score,
    }


def format_clarity_context_section(context: Optional[dict[str, Any]]) -> str:
    """Render pre-computed clarity metrics for the clarity diagnostic prompt."""
    if not context:
        return ""

    signal_lines = []
    for signal in context.get("signals") or []:
        signal_lines.append(
            f"- {signal['check']}: {signal['status']} — {signal.get('note', '')}"
            + (f" (value: {signal['value']})" if signal.get("value") is not None else "")
        )

    metrics_block = "\n".join(
        [
            f"- Word count: {context.get('word_count', 0)}",
            f"- Sentences: {context.get('sentence_count', 0)}",
            f"- Avg words/sentence: {context.get('avg_words_per_sentence', 0)}",
            f"- Flesch–Kincaid grade: {context.get('flesch_kincaid_grade')}",
            f"- Jargon density: {context.get('jargon_density_percent')}%",
            f"- Paragraphs: {context.get('paragraph_count', 0)} "
            f"(longest ~{context.get('max_paragraph_words', 0)} words)",
            f"- Line breaks: {context.get('line_break_count', 0)}; "
            f"bullet-like lines: {context.get('bullet_line_count', 0)}",
            f"- Wall-of-text flag: {context.get('wall_of_text', False)}",
        ]
    )

    return (
        "Evidence from deterministic clarity / cognitive-load checks "
        "(use this to ground your score; do not re-derive these numbers):\n"
        f"- Overall deterministic clarity score: {context.get('deterministic_score')}/10\n"
        f"{metrics_block}\n"
        "Signal detail:\n"
        + ("\n".join(signal_lines) if signal_lines else "- (none)")
        + "\n\nBase your clarity score primarily on whether a mobile LinkedIn reader "
        "can grasp the point quickly. Cite these metrics in flaws/improvements when relevant. "
        "Prefer concrete structure fixes (shorter paragraphs, line breaks, simpler words) "
        "over vague 'make it clearer' advice."
    )
