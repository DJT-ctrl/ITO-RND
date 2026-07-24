"""T7.9 + T7.10 combined visual diagnostics (Gemini multimodal, opt-in).

One agent covers:
  - T7.9 Visual hierarchy — contrast, clutter, mobile thumbnail readability
  - T7.10 OCR & asset alignment — extract on-image text; compare to caption

Off by default via settings.visual_diagnostics_enabled / request override.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, ImageUrl, RunContext

from agents.prompt_safety import (
    PROMPT_DATA_PREAMBLE,
    build_evaluation_user_message,
    wrap_untrusted_text,
)
from agents.schemas import EvaluationDeps, build_voice_profile_section
from agents.structured_output import agent_structured_output
from config.settings import Settings, pydantic_ai_gemini_model

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_EXT_TO_MEDIA = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

VisualUserPrompt = Union[str, Sequence[Union[str, BinaryContent, ImageUrl]]]


class VisualDiagnosticOutput(BaseModel):
    """Combined T7.9 + T7.10 output; includes DiagnosticOutput-compatible fields."""

    score: float = Field(..., ge=0, le=10, description="Overall visual quality 0–10.")
    flaws: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    # T7.9
    contrast_pass: bool = Field(..., description="True if contrast looks mobile-readable.")
    visual_clutter: str = Field(
        ...,
        description="Clutter level: low, medium, or high.",
    )
    hierarchy_critique: str = Field(
        default="",
        description="Short critique of focal point / text-to-graphic balance.",
    )
    # T7.10
    extracted_text: str = Field(
        default="",
        description="Visible text read from the image (OCR-like).",
    )
    copy_alignment_score: float = Field(
        ...,
        ge=0,
        le=10,
        description="How well on-image text matches the post caption (0–10).",
    )
    alignment_notes: str = Field(
        default="",
        description="Mismatch / clickbait notes between image text and caption.",
    )


def resolve_use_visual_diagnostics(
    settings: Settings,
    use_visual_diagnostics: Optional[bool] = None,
) -> bool:
    """Request override wins; otherwise settings (default False)."""
    if use_visual_diagnostics is not None:
        return bool(use_visual_diagnostics)
    return bool(settings.visual_diagnostics_enabled)


def _guess_media_type(url: str, content_type: Optional[str]) -> Optional[str]:
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in ALLOWED_MEDIA_TYPES:
            return base
        if base == "image/jpg":
            return "image/jpeg"
    lower = (url or "").lower().split("?", 1)[0]
    for ext, media in _EXT_TO_MEDIA.items():
        if lower.endswith(ext):
            return media
    return None


def fetch_image_from_url(url: str) -> tuple[Optional[bytes], Optional[str], list[str]]:
    """Download image bytes with size/type guards. Soft-fail with warnings."""
    warnings: list[str] = []
    cleaned = (url or "").strip()
    if not cleaned:
        return None, None, warnings
    if not cleaned.startswith(("http://", "https://")):
        warnings.append("visual: image_url must be http(s); skipped.")
        return None, None, warnings

    try:
        req = Request(cleaned, headers={"User-Agent": "ITO-VisualDiagnostics/1.0"})
        with urlopen(req, timeout=15) as resp:  # noqa: S310 — caller-supplied URL, guarded
            raw_type = resp.headers.get("Content-Type")
            data = resp.read(MAX_IMAGE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        warnings.append(f"visual: failed to fetch image_url ({exc}); skipped.")
        return None, None, warnings

    if len(data) > MAX_IMAGE_BYTES:
        warnings.append(
            f"visual: image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit; skipped."
        )
        return None, None, warnings

    media_type = _guess_media_type(cleaned, raw_type)
    if media_type is None:
        warnings.append(
            "visual: unsupported image type (use jpeg/png/webp); skipped."
        )
        return None, None, warnings

    return data, media_type, warnings


def prepare_visual_image(
    *,
    image_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_media_type: Optional[str] = None,
) -> tuple[Optional[bytes], Optional[str], Optional[str], list[str]]:
    """Resolve upload bytes or URL into (bytes, media_type, url, warnings)."""
    warnings: list[str] = []

    if image_bytes:
        if len(image_bytes) > MAX_IMAGE_BYTES:
            warnings.append(
                f"visual: uploaded image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB; skipped."
            )
            return None, None, None, warnings
        media = (image_media_type or "").split(";")[0].strip().lower()
        if media == "image/jpg":
            media = "image/jpeg"
        if media not in ALLOWED_MEDIA_TYPES:
            warnings.append(
                "visual: unsupported upload type (use jpeg/png/webp); skipped."
            )
            return None, None, None, warnings
        return image_bytes, media, image_url, warnings

    if image_url:
        data, media, fetch_warnings = fetch_image_from_url(image_url)
        warnings.extend(fetch_warnings)
        return data, media, image_url if data else None, warnings

    return None, None, None, warnings


def build_visual_system_prompt(deps: EvaluationDeps) -> str:
    voice_section = build_voice_profile_section(deps.voice_profile)
    draft_section = wrap_untrusted_text(deps.draft_content)
    return f"""
{PROMPT_DATA_PREAMBLE}

You are the Visual Diagnostics worker (T7.9 hierarchy + T7.10 OCR/alignment) in a
LinkedIn post evaluation pipeline. You receive the draft caption AND the attached
image. Judge the image for feed/thumbnail performance and whether on-image text
matches the caption.
{voice_section}
Draft caption (text only — evaluate alignment against the image):
{draft_section}

Return structured data only:
- score: overall visual quality 0–10 (hierarchy + alignment combined).
- flaws / advantages / improvements: concrete, practical bullets.
- contrast_pass: true if contrast looks readable on a phone feed.
- visual_clutter: one of low | medium | high.
- hierarchy_critique: short note on focal point / text-to-graphic balance.
- extracted_text: all readable text from the image (empty string if none).
- copy_alignment_score: 0–10 how well image text matches the caption intent.
- alignment_notes: clickbait / mismatch notes (empty if aligned).

Be direct. Do not invent pixels you cannot see.
""".strip()


def build_visual_user_prompt(deps: EvaluationDeps) -> VisualUserPrompt:
    """Multimodal user message: wrapped caption + image part."""
    parts: list[Union[str, BinaryContent, ImageUrl]] = [
        build_evaluation_user_message(deps.draft_content),
        (
            "Attached image is the draft's LinkedIn visual/thumbnail. "
            "Use it for hierarchy + OCR alignment."
        ),
    ]
    if deps.image_bytes and deps.image_media_type:
        parts.append(
            BinaryContent(data=deps.image_bytes, media_type=deps.image_media_type)
        )
    elif deps.image_url:
        parts.append(ImageUrl(url=deps.image_url))
    return parts


def build_visual_agent(model: Any = None) -> Agent[EvaluationDeps, VisualDiagnosticOutput]:
    resolved = pydantic_ai_gemini_model() if model is None else model
    agent: Agent[EvaluationDeps, VisualDiagnosticOutput] = Agent(
        resolved,
        deps_type=EvaluationDeps,
        output_type=agent_structured_output(VisualDiagnosticOutput, resolved),
        retries=2,
    )

    @agent.system_prompt
    def visual_system_prompt(ctx: RunContext[EvaluationDeps]) -> str:
        return build_visual_system_prompt(ctx.deps)

    return agent
