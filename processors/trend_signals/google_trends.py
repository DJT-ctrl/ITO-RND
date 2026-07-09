"""Google Trends freshness signals via pytrends (Tier 2 discoverability)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config.settings import Settings

DEFAULT_CACHE_PATH = Path("data/processed/trend_cache.json")
DEFAULT_TIMEFRAME = "today 3-m"
TRENDS_DISCLAIMER = (
    "Google Trends reflects web-wide search interest, not LinkedIn feed performance. "
    "Use only as a timeliness hint."
)


def fetch_trend_signals(
    keywords: list[str],
    settings: Settings,
    corpus_top_topics: Optional[list[dict[str, Any]]] = None,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Fetch or load cached trend signals for draft-derived keywords only."""
    if not keywords:
        return None, []

    warnings: list[str] = []
    signals: list[dict[str, Any]] = []

    for keyword in keywords:
        cached = _load_cached_signal(keyword, settings)
        if cached is not None:
            signals.append(cached)
            continue

        try:
            signal = _fetch_keyword_signal(keyword, settings)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully on any pytrends/network error
            warnings.append(f"Google Trends lookup failed for '{keyword}': {exc}")
            continue

        signal["corpus_alignment"] = _corpus_alignment(keyword, signal["direction"], corpus_top_topics)
        _save_cached_signal(keyword, settings, signal)
        signals.append(signal)

    if not signals:
        return None, warnings

    return {
        "disclaimer": TRENDS_DISCLAIMER,
        "keywords": keywords,
        "signals": signals,
    }, warnings


def format_trends_for_prompt(trends: Optional[dict[str, Any]]) -> Optional[str]:
    """Render compact trend evidence for the SEO prompt."""
    if not trends or not trends.get("signals"):
        return None

    lines = [
        "External trend signal (Google Trends — web-wide, NOT LinkedIn-specific):",
        f"- Disclaimer: {trends.get('disclaimer', TRENDS_DISCLAIMER)}",
    ]
    for signal in trends["signals"]:
        keyword = signal.get("keyword", "")
        direction = signal.get("direction", "unknown")
        recent = signal.get("recent_avg")
        prior = signal.get("prior_avg")
        alignment = signal.get("corpus_alignment", "unknown")
        metric = ""
        if recent is not None and prior is not None:
            metric = f" (recent avg {recent:.0f} vs prior {prior:.0f})"
        lines.append(
            f'- Keyword "{keyword}": {direction}{metric}. Corpus alignment: {alignment}.'
        )
    lines.append(
        "Treat this as a timeliness hint only. Corpus evidence and deterministic checks remain primary."
    )
    return "\n".join(lines)


def classify_direction(series: pd.Series) -> tuple[str, Optional[float], Optional[float]]:
    """Compare mean interest in the last 4 weeks vs the prior 8 weeks."""
    if series.empty or len(series) < 14:
        return "insufficient_data", None, None

    values = series.dropna()
    if len(values) < 14:
        return "insufficient_data", None, None

    recent = values.tail(28)
    prior = values.iloc[-84:-28] if len(values) > 28 else values.iloc[:-28]
    if prior.empty:
        return "insufficient_data", None, None

    recent_avg = float(recent.mean())
    prior_avg = float(prior.mean())
    if prior_avg == 0:
        direction = "rising" if recent_avg > 0 else "flat"
    else:
        change_ratio = (recent_avg - prior_avg) / prior_avg
        if change_ratio >= 0.15:
            direction = "rising"
        elif change_ratio <= -0.15:
            direction = "falling"
        else:
            direction = "flat"

    return direction, recent_avg, prior_avg


def _fetch_keyword_signal(keyword: str, settings: Settings) -> dict[str, Any]:
    from pytrends.request import TrendReq

    pytrends = TrendReq(hl="en-US", tz=0, retries=2, backoff_factor=0.5)
    pytrends.build_payload(
        kw_list=[keyword],
        timeframe=DEFAULT_TIMEFRAME,
        geo=settings.google_trends_geo,
    )
    df = pytrends.interest_over_time()
    if df is None or df.empty or keyword not in df.columns:
        raise ValueError("no interest data returned")

    direction, recent_avg, prior_avg = classify_direction(df[keyword])
    return {
        "keyword": keyword,
        "direction": direction,
        "recent_avg": recent_avg,
        "prior_avg": prior_avg,
        "timeframe": DEFAULT_TIMEFRAME,
        "geo": settings.google_trends_geo,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _corpus_alignment(
    keyword: str,
    direction: str,
    corpus_top_topics: Optional[list[dict[str, Any]]],
) -> str:
    corpus_terms = {str(entry.get("topic", "")).strip().lower() for entry in (corpus_top_topics or [])}
    corpus_terms.discard("")
    keyword_lower = keyword.lower()
    in_corpus = any(
        keyword_lower in topic or topic in keyword_lower for topic in corpus_terms
    )

    if direction in ("falling", "flat", "insufficient_data"):
        return "stale"
    if in_corpus:
        return "aligned"
    return "web_trend_only"


def _cache_key(keyword: str, settings: Settings) -> str:
    geo = settings.google_trends_geo or "GLOBAL"
    return f"{keyword.lower()}|{geo}|{DEFAULT_TIMEFRAME}"


def _load_cache(path: Optional[Path] = None) -> dict[str, Any]:
    resolved = path or DEFAULT_CACHE_PATH
    if not resolved.exists():
        return {}
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, Any], path: Optional[Path] = None) -> None:
    resolved = path or DEFAULT_CACHE_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_cache_stale(entry: dict[str, Any], ttl_hours: int) -> bool:
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return True
    try:
        created = datetime.fromisoformat(fetched_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        return age_hours >= ttl_hours
    except ValueError:
        return True


def _load_cached_signal(keyword: str, settings: Settings) -> Optional[dict[str, Any]]:
    cache = _load_cache()
    entry = cache.get(_cache_key(keyword, settings))
    if entry is None or _is_cache_stale(entry, settings.google_trends_cache_ttl_hours):
        return None
    return entry


def _save_cached_signal(keyword: str, settings: Settings, signal: dict[str, Any]) -> None:
    cache = _load_cache()
    cache[_cache_key(keyword, settings)] = signal
    _save_cache(cache)
