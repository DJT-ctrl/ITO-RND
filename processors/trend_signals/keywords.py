"""Deterministic keyword extraction from draft text for Google Trends lookups."""

from __future__ import annotations

import re
from typing import Any, Optional

_FIRST_SENTENCE_RE = re.compile(r"^[^.!?\n]+")
_HASHTAG_RE = re.compile(r"#(\w+)")

_STOPWORDS = frozenset(
    """
    a an the and or but in on at to for of is are was were be been being
    i we you they he she it this that these those my our your their
    with from as by about into through after before over under again
    very just so than too also not no nor only own same such can will
    excited thrilled proud announce announcing announcement sharing share
    happy delighted honored grateful check out link below read more
    """.split()
)

_FILLER_WORDS = frozenset(
    {
        "excited",
        "thrilled",
        "proud",
        "announce",
        "announcing",
        "announcement",
        "sharing",
        "share",
        "happy",
        "delighted",
        "honored",
        "grateful",
        "launch",
        "launching",
    }
)


def extract_trend_keywords(
    draft: str,
    corpus_top_topics: Optional[list[dict[str, Any]]] = None,
    max_keywords: int = 3,
) -> list[str]:
    """Return 1–3 search terms derived only from the draft (never global trends)."""
    candidates: list[str] = []

    for match in _HASHTAG_RE.finditer(draft):
        tag = match.group(1).strip()
        if _is_valid_keyword(tag):
            candidates.append(tag.replace("_", " "))

    first_sentence = _first_sentence(draft)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", first_sentence):
        lower = token.lower()
        if lower in _STOPWORDS or lower in _FILLER_WORDS:
            continue
        if len(token) < 3:
            continue
        candidates.append(token)

    bigrams = _extract_bigrams(first_sentence)
    candidates.extend(bigrams)

    corpus_terms = _corpus_topic_terms(corpus_top_topics)
    ranked = _rank_candidates(candidates, corpus_terms)

    seen: set[str] = set()
    keywords: list[str] = []
    for candidate in ranked:
        normalized = candidate.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(candidate.strip())
        if len(keywords) >= max_keywords:
            break

    return keywords


def _first_sentence(draft: str) -> str:
    match = _FIRST_SENTENCE_RE.search(draft.strip())
    return match.group(0).strip() if match else draft.strip()[:160]


def _extract_bigrams(sentence: str) -> list[str]:
    words = [
        w.lower()
        for w in re.findall(r"[A-Za-z][A-Za-z0-9-]*", sentence)
        if w.lower() not in _STOPWORDS and w.lower() not in _FILLER_WORDS and len(w) >= 3
    ]
    bigrams: list[str] = []
    for index in range(len(words) - 1):
        bigrams.append(f"{words[index]} {words[index + 1]}")
    return bigrams


def _corpus_topic_terms(corpus_top_topics: Optional[list[dict[str, Any]]]) -> set[str]:
    if not corpus_top_topics:
        return set()
    terms: set[str] = set()
    for entry in corpus_top_topics:
        topic = str(entry.get("topic", "")).strip().lower()
        if topic:
            terms.add(topic)
            terms.update(part for part in topic.split() if len(part) >= 3)
    return terms


def _rank_candidates(candidates: list[str], corpus_terms: set[str]) -> list[str]:
    def score(candidate: str) -> tuple[int, int]:
        lower = candidate.lower()
        corpus_hit = int(any(term in lower or lower in term for term in corpus_terms))
        return (corpus_hit, len(candidate))

    unique = list(dict.fromkeys(candidates))
    return sorted(unique, key=score, reverse=True)


def _is_valid_keyword(text: str) -> bool:
    lower = text.lower()
    return len(lower) >= 3 and lower not in _STOPWORDS and lower not in _FILLER_WORDS
