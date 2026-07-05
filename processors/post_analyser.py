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
import re
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types as genai_types

from config.settings import Settings


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_HOOK_TYPES = ("question", "bold_statement", "story", "list", "announcement", "other")
_TONES = ("professional", "casual", "emotional", "humorous", "urgent")

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

# Gemini prompt — pre-computed stats are injected so the model never has to
# recount numbers, keeping it focused on language understanding only.
_GEMINI_PROMPT = """\
Analyse the LinkedIn post below and return ONLY a JSON object with these keys:

{{
  "hook_type": one of [{hook_types}],
  "tone": one of [{tones}],
  "topic": "2–4 word label for what this post is about",
  "has_explicit_cta": true or false  (true only if the author explicitly tells readers to DO something, e.g. "comment below", "DM me", "click the link"),
  "writing_style": "one sentence describing how this post is structured"
}}

POST TEXT:
\"\"\"{content}\"\"\"

Pre-computed context (do NOT re-derive — use for broader understanding only):
- word_count: {word_count}
- hashtag_count: {hashtag_count}
- has_media: {has_media}
"""


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

    def _ensure_gemini(self) -> None:
        """Initialise the Gemini client on first use. Raises if key is absent."""
        if self._model is not None:
            return
        if not self._settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set (check your .env file).")
        self._client = genai.Client(api_key=self._settings.gemini_api_key)
        self._model = True  # sentinel — client is the real handle

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

        posted_dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else None

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
            "hour_of_day": posted_dt.hour if posted_dt else None,
            "day_of_week": posted_dt.strftime("%A") if posted_dt else None,
        }

    # ── Stage 2 ───────────────────────────────────────────────────────────────

    def compute_gemini_features(
        self, post: dict[str, Any], python_features: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract qualitative signals via Gemini. One API call per post.

        Returns empty placeholders (not raises) on a bad response so one
        problematic post never kills the whole batch.
        """
        self._ensure_gemini()
        content: str = post.get("content") or ""
        prompt = _GEMINI_PROMPT.format(
            hook_types=", ".join(_HOOK_TYPES),
            tones=", ".join(_TONES),
            content=content,
            word_count=python_features["word_count"],
            hashtag_count=python_features["hashtag_count"],
            has_media=python_features["has_media"],
        )
        try:
            response = self._client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return json.loads(response.text)
        except Exception:  # noqa: BLE001 — bad response should never crash a batch
            return {k: None for k in ("hook_type", "tone", "topic", "has_explicit_cta", "writing_style")}
