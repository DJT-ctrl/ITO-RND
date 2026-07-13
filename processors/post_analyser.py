"""Converts one raw LinkedIn post dict → a flat, analysis-ready feature record.

Two deliberate stages keep costs down and hallucinations out:

  Stage 1 – Python features
    Pure math and string operations on the raw JSON.  Free, instant, no AI.
    Run this for the whole dataset before deciding to spend API credits.

  Stage 2 – Gemini features
    One API call per post for qualitative signals that only a language model
    can extract reliably (hook type, tone, topic, etc.).  Pre-computed numeric
    context is injected into the prompt so Gemini never has to re-derive numbers
    — it just interprets the text.  JSON-mode response eliminates free-form
    rambling and makes the output directly parseable.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from google import genai
from google.genai import types as genai_types

from processors.gemini_retry import call_with_gemini_retry

from agents.prompt_safety import (
    PROMPT_DATA_PREAMBLE,
    escape_tag_breakout,
    sanitize_known_injection_patterns,
)
from config.settings import GEMINI_MODEL, Settings
from processors.post_timing import build_post_timing_fields, infer_timezone_from_location

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_HOOK_TYPES = ("question", "bold_statement", "story", "list", "announcement", "other")
_TONES = ("professional", "casual", "emotional", "humorous", "urgent")
_GEMINI_FEATURE_KEYS = ("hook_type", "tone", "topic", "has_explicit_cta", "writing_style")
DEFAULT_GEMINI_MODEL = GEMINI_MODEL
# Covers the most common Unicode emoji blocks without pulling in a full library.
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F680-\U0001F6FF"   # transport & map
    "\U0001F1E0-\U0001F1FF"   # flags
    "\U00002700-\U000027BF"   # dingbats
    "\U0001F900-\U0001F9FF"   # supplemental symbols
    "\U00002600-\U000026FF"   # misc symbols
    "]",
    flags=re.UNICODE,
)

# Gemini prompt — uses __PLACEHOLDER__ tokens (not str.format) so post text
# with curly braces cannot break prompt construction.
_GEMINI_PROMPT_TEMPLATE = """\
__PREAMBLE__

Analyse the LinkedIn post below and return ONLY a JSON object with these keys:

{
  "hook_type": one of [__HOOK_TYPES__],
  "tone": one of [__TONES__],
  "topic": "2–4 word label for what this post is about",
  "has_explicit_cta": true or false  (true only if the author explicitly tells readers to DO something, e.g. "comment below", "DM me", "click the link"),
  "writing_style": "one sentence describing how this post is structured"
}

POST TEXT:
<post_content>
__CONTENT__
</post_content>

Pre-computed context (do NOT re-derive — use for broader understanding only):
- word_count: __WORD_COUNT__
- hashtag_count: __HASHTAG_COUNT__
- has_media: __HAS_MEDIA__
"""


def _build_gemini_prompt(
    *,
    content: str,
    word_count: int,
    hashtag_count: int,
    has_media: bool,
) -> str:
    safe_content = sanitize_known_injection_patterns(escape_tag_breakout(content))
    return (
        _GEMINI_PROMPT_TEMPLATE.replace("__PREAMBLE__", PROMPT_DATA_PREAMBLE)
        .replace("__HOOK_TYPES__", ", ".join(_HOOK_TYPES))
        .replace("__TONES__", ", ".join(_TONES))
        .replace("__CONTENT__", safe_content)
        .replace("__WORD_COUNT__", str(word_count))
        .replace("__HASHTAG_COUNT__", str(hashtag_count))
        .replace("__HAS_MEDIA__", str(has_media))
    )


# ──────────────────────────────────────────────────────────────────────────────
# Analyser
# ──────────────────────────────────────────────────────────────────────────────

class PostAnalyser:
    """Extracts a flat feature record from one raw LinkedIn post dict.

    Typical usage::

        analyser = PostAnalyser(settings)
        python_features = analyser.compute_python_features(post)
        gemini_features = analyser.compute_gemini_features(post, python_features)
        full_record = {**python_features, **gemini_features}
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None  # lazy — only initialised if Stage 2 is called
        self.last_error: Optional[str] = None

    def _fail(self, message: str) -> dict[str, None]:
        """Record a Stage 2 failure and return the standard empty feature dict."""
        self.last_error = message
        logger.error(message)
        return self._empty_gemini_features()

    def _ensure_gemini(self) -> None:
        """Initialise the Gemini client on first use. Raises if key is absent."""
        if self._model is not None:
            return
        if not self._settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set (check your .env file).")
        self._client = genai.Client(api_key=self._settings.gemini_api_key)
        self._model = DEFAULT_GEMINI_MODEL

    @staticmethod
    def _empty_gemini_features() -> dict[str, None]:
        return {k: None for k in _GEMINI_FEATURE_KEYS}

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        text = getattr(response, "text", None)
        if text:
            return text.strip()
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text.strip()
        return ""

    def _call_gemini(self, prompt: str) -> str:
        """Call Gemini with retries on transient API errors."""

        def _request() -> str:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return self._extract_response_text(response)

        return call_with_gemini_retry(_request, label="Gemini Stage 2")

    # ── Stage 1 ───────────────────────────────────────────────────────────────

    def compute_python_features(self, post: dict[str, Any]) -> dict[str, Any]:
        """Derive everything that is just math or string ops — no AI needed."""
        content: str = post.get("content") or ""
        engagement: dict = post.get("engagement") or {}
        images: list = post.get("postImages") or []
        author: dict = post.get("author") or {}
        ts = (post.get("postedAt") or {}).get("timestamp")

        likes = int(engagement.get("likes") or 0)
        comments = int(engagement.get("comments") or 0)
        shares = int(engagement.get("shares") or 0)
        total = likes + comments + shares

        location_text = post.get("location_text")
        tz_name = infer_timezone_from_location(location_text) if location_text else None
        timing = build_post_timing_fields(ts, tz_name)

        follower_count = post.get("follower_count")
        if follower_count is not None:
            follower_count = int(follower_count)
            engagement_rate = round(total / follower_count, 4) if follower_count > 0 else None
        else:
            follower_count = None
            engagement_rate = None

        return {
            # ── identity (join keys, not analysis features) ──────────────────
            # `.get(key, default)` only falls back when the key is MISSING —
            # real LinkedIn scrapes sometimes have the key present but
            # explicitly null (e.g. an anonymized author), so `or ""` is
            # needed to also catch that case.
            "post_id": post.get("id") or "",
            "author_public_id": author.get("publicIdentifier") or "",
            "linkedin_url": post.get("linkedinUrl") or "",
            # ── engagement ───────────────────────────────────────────────────
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "total_engagement": total,
            # Ratios expose content quality independent of audience size.
            "comment_ratio": round(comments / likes, 3) if likes else None,
            "share_ratio": round(shares / likes, 3) if likes else None,
            # ── content shape ────────────────────────────────────────────────
            "word_count": len(content.split()),
            "char_count": len(content),
            "hashtag_count": content.count("#"),
            "emoji_count": len(_EMOJI_RE.findall(content)),
            "has_media": len(images) > 0,
            "is_job_post": bool(post.get("job")),
            # ── timing ───────────────────────────────────────────────────────
            "hour_of_day": timing["hour_of_day"],
            "day_of_week": timing["day_of_week"],
            # ── enrichment fields (T6 Point 1) ──────────────────────────────
            "follower_count": follower_count,
            "engagement_rate": engagement_rate,
            "author_location_text": location_text,
            "author_timezone": timing["author_timezone"],
        }

    # ── Stage 2 ───────────────────────────────────────────────────────────────

    def compute_gemini_features(
        self, post: dict[str, Any], python_features: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract qualitative signals via Gemini. One API call per post.

        Returns empty placeholders (not raises) on a bad response so one
        problematic post never kills the whole batch.
        """
        self.last_error = None
        self._ensure_gemini()
        post_id = post.get("id") or python_features.get("post_id") or "unknown"
        content: str = post.get("content") or ""
        if not content.strip():
            return self._fail(f"Post {post_id}: empty content — skipping Gemini Stage 2")

        prompt = _build_gemini_prompt(
            content=content,
            word_count=python_features["word_count"],
            hashtag_count=python_features["hashtag_count"],
            has_media=python_features["has_media"],
        )
        try:
            raw_text = self._call_gemini(prompt)
            if not raw_text:
                return self._fail(f"Post {post_id}: Gemini returned empty response (model={self._model})")

            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                return self._fail(
                    f"Post {post_id}: Gemini JSON was {type(parsed).__name__}, expected object — "
                    f"raw={raw_text[:200]!r}"
                )

            missing = [k for k in _GEMINI_FEATURE_KEYS if k not in parsed]
            if missing:
                logger.warning(
                    "Post %s: Gemini JSON missing keys %s — raw=%r",
                    post_id,
                    missing,
                    raw_text[:200],
                )

            return {key: parsed.get(key) for key in _GEMINI_FEATURE_KEYS}
        except json.JSONDecodeError as exc:
            return self._fail(
                f"Post {post_id}: invalid Gemini JSON ({exc}) — "
                f"raw={raw_text[:200]!r}" if "raw_text" in locals() else f"Post {post_id}: invalid Gemini JSON ({exc})"
            )
        except Exception as exc:  # noqa: BLE001 — one bad post must not kill the batch
            return self._fail(f"Post {post_id}: Gemini Stage 2 failed — {type(exc).__name__}: {exc}")


def verify_gemini_api(settings: Settings) -> tuple[bool, str]:
    """Cheap probe — confirms the configured model/key work before a batch run."""
    if not settings.gemini_api_key:
        return False, "GEMINI_API_KEY is not set (check .env in the project root)."
    analyser = PostAnalyser(settings)
    probe_post = {
        "id": "gemini-probe",
        "content": "Quick connectivity probe — reply with JSON only.",
        "engagement": {},
        "postImages": [],
        "author": {},
        "postedAt": {},
    }
    python_features = analyser.compute_python_features(probe_post)
    result = analyser.compute_gemini_features(probe_post, python_features)
    if result.get("hook_type"):
        return True, f"Model `{DEFAULT_GEMINI_MODEL}` responded OK."
    return False, analyser.last_error or "Probe returned empty features."
