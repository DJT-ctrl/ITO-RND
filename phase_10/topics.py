"""Coarse niche taxonomy for Phase 10 (T10.6).

Maps free-text analyser ``topic`` labels onto a stable enum used for
``posts.niche``, ``user_niches``, and search-plan weights.
"""

from __future__ import annotations

NICHES: tuple[str, ...] = (
    "sports",
    "saas_b2b",
    "fintech",
    "creator",
    "finance",
    "health",
    "career",
    "marketing",
    "ai_tech",
    "other",
)

DEFAULT_NICHE = "other"

# Longer / more specific phrases first within each niche.
_ALIAS_TO_NICHE: tuple[tuple[str, str], ...] = (
    ("saas b2b", "saas_b2b"),
    ("b2b saas", "saas_b2b"),
    ("software as a service", "saas_b2b"),
    ("product-led growth", "saas_b2b"),
    ("product led growth", "saas_b2b"),
    ("startup", "saas_b2b"),
    ("saas", "saas_b2b"),
    ("b2b", "saas_b2b"),
    ("fintech", "fintech"),
    ("payment", "fintech"),
    ("banking app", "fintech"),
    ("neobank", "fintech"),
    ("crypto", "fintech"),
    ("blockchain", "fintech"),
    ("personal finance", "finance"),
    ("investing", "finance"),
    ("investment", "finance"),
    ("stock market", "finance"),
    ("wealth", "finance"),
    ("accounting", "finance"),
    ("finance", "finance"),
    ("money", "finance"),
    ("content creator", "creator"),
    ("creator economy", "creator"),
    ("influencer", "creator"),
    ("youtube", "creator"),
    ("tiktok", "creator"),
    ("newsletter", "creator"),
    ("creator", "creator"),
    ("mental health", "health"),
    ("wellness", "health"),
    ("fitness", "health"),
    ("healthcare", "health"),
    ("medical", "health"),
    ("health", "health"),
    ("job search", "career"),
    ("job hiring", "career"),
    ("hiring", "career"),
    ("recruiting", "career"),
    ("career advice", "career"),
    ("resume", "career"),
    ("interview", "career"),
    ("career", "career"),
    ("leadership", "career"),
    ("digital marketing", "marketing"),
    ("content marketing", "marketing"),
    ("growth marketing", "marketing"),
    ("branding", "marketing"),
    ("advertising", "marketing"),
    ("seo", "marketing"),
    ("marketing", "marketing"),
    ("generative ai", "ai_tech"),
    ("llm", "ai_tech"),
    ("chatgpt", "ai_tech"),
    ("ai tools", "ai_tech"),
    ("ai tech", "ai_tech"),
    ("software engineering", "ai_tech"),
    ("programming", "ai_tech"),
    ("developer", "ai_tech"),
    ("artificial intelligence", "ai_tech"),
    ("machine learning", "ai_tech"),
    ("football", "sports"),
    ("soccer", "sports"),
    ("basketball", "sports"),
    ("tennis", "sports"),
    ("athlete", "sports"),
    ("sports", "sports"),
    ("nfl", "sports"),
    ("nba", "sports"),
)


def is_valid_niche(value: str | None) -> bool:
    return bool(value) and value in NICHES


def queries_for_niche(niche: str, *, limit: int = 5) -> list[str]:
    """LinkedIn search queries for a niche (niche id + taxonomy aliases)."""
    if not is_valid_niche(niche) or niche == DEFAULT_NICHE:
        return []
    out: list[str] = []
    seen: set[str] = set()
    candidates = [niche.replace("_", " "), niche]
    for alias, mapped in _ALIAS_TO_NICHE:
        if mapped == niche:
            candidates.append(alias)
    for raw in candidates:
        q = " ".join(str(raw).strip().lower().split())
        if not q or q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= limit:
            break
    return out


def normalize_topic_to_niche(free_text: str | None) -> str:
    """Map a Gemini free-text topic (or similar) onto the coarse niche enum."""
    if free_text is None:
        return DEFAULT_NICHE
    text = " ".join(str(free_text).strip().lower().split())
    if not text:
        return DEFAULT_NICHE
    if text in NICHES:
        return text
    underscored = text.replace(" ", "_").replace("-", "_")
    if underscored in NICHES:
        return underscored
    # Whole-token "ai" → ai_tech (avoid matching inside unrelated words).
    tokens = set(text.replace("-", " ").split())
    if "ai" in tokens:
        return "ai_tech"
    for alias, niche in _ALIAS_TO_NICHE:
        if alias in text:
            return niche
    return DEFAULT_NICHE
