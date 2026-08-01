"""Gemini Pro structured critic for agentic digests (T10.10)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types as genai_types

from config.settings import Settings
from processors.gemini_retry import call_with_gemini_retry
from telemetry.pricing import cost_from_tokens

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "warn": 1, "critical": 2}
_VALID_SEVERITIES = frozenset(_SEVERITY_RANK)
_VALID_CATEGORIES = frozenset(
    {"budget", "scrape", "search_plan", "validation", "feedback", "workers", "other"}
)

SYSTEM_INSTRUCTION = """\
You are a read-only DevOps critic for an agentic LinkedIn content pipeline.
You receive a JSON ops snapshot (budget, job runs, search plan, scrape proofs,
validation MAE, feedback queue, Apify spend, synthesized errors).

Rules:
- Advise only. Never claim you changed config, flags, prompts, or seeds.
- Cite concrete numbers / job_ids / niches from the snapshot as evidence.
- If data is sparse or missing, say so; do not invent metrics.
- Prefer actionable suggested_action phrasing for a human operator.
- severity must be one of: info, warn, critical.
- category must be one of: budget, scrape, search_plan, validation, feedback, workers, other.

Respond with JSON only matching this shape:
{
  "severity": "info|warn|critical",
  "summary_markdown": "short narrative",
  "findings": [
    {
      "title": "...",
      "severity": "info|warn|critical",
      "category": "budget|scrape|search_plan|validation|feedback|workers|other",
      "evidence": "...",
      "suggested_action": "..."
    }
  ],
  "budget_warning": "string or null"
}
"""


@dataclass(frozen=True)
class CriticResult:
    severity: str
    summary_markdown: str
    findings: list[dict[str, Any]]
    budget_warning: str | None
    payload: dict[str, Any]
    model: str
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0


def _normalize_severity(raw: Any) -> str:
    value = str(raw or "info").strip().lower()
    if value in {"warning", "warn"}:
        return "warn"
    if value in _VALID_SEVERITIES:
        return value
    return "info"


def _max_severity(*values: str) -> str:
    best = "info"
    for value in values:
        sev = _normalize_severity(value)
        if _SEVERITY_RANK[sev] > _SEVERITY_RANK[best]:
            best = sev
    return best


def _normalize_finding(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    category = str(raw.get("category") or "other").strip().lower()
    if category not in _VALID_CATEGORIES:
        category = "other"
    return {
        "title": title,
        "severity": _normalize_severity(raw.get("severity")),
        "category": category,
        "evidence": str(raw.get("evidence") or "").strip(),
        "suggested_action": str(raw.get("suggested_action") or "").strip(),
    }


def parse_critic_response(raw_text: str, *, model: str) -> CriticResult:
    """Parse and normalize critic JSON; tolerate malformed model output."""
    payload: dict[str, Any]
    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("root is not an object")
        payload = parsed
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Pro digest JSON parse failed: %s", exc)
        summary = (
            "Critic returned unparseable output. Raw excerpt:\n\n"
            f"```\n{raw_text[:2000]}\n```"
        )
        return CriticResult(
            severity="warn",
            summary_markdown=summary,
            findings=[],
            budget_warning=None,
            payload={
                "severity": "warn",
                "summary_markdown": summary,
                "findings": [],
                "budget_warning": None,
                "parse_error": str(exc),
                "raw_excerpt": raw_text[:2000],
            },
            model=model,
            cost_usd=0.0,
        )

    findings_raw = payload.get("findings")
    findings: list[dict[str, Any]] = []
    if isinstance(findings_raw, list):
        for item in findings_raw:
            normalized = _normalize_finding(item)
            if normalized:
                findings.append(normalized)

    top = _normalize_severity(payload.get("severity"))
    finding_sevs = [f["severity"] for f in findings]
    severity = _max_severity(top, *finding_sevs) if finding_sevs else top

    summary = str(payload.get("summary_markdown") or "").strip()
    if not summary:
        if findings:
            summary = "; ".join(f["title"] for f in findings[:5])
        else:
            summary = "No findings — snapshot looked quiet or sparse."

    budget_warning = payload.get("budget_warning")
    if budget_warning is not None:
        budget_warning = str(budget_warning).strip() or None

    normalized_payload = {
        "severity": severity,
        "summary_markdown": summary,
        "findings": findings,
        "budget_warning": budget_warning,
    }
    return CriticResult(
        severity=severity,
        summary_markdown=summary,
        findings=findings,
        budget_warning=budget_warning,
        payload=normalized_payload,
        model=model,
        cost_usd=0.0,
    )


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


def _usage_tokens(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    input_tokens = int(
        getattr(usage, "prompt_token_count", None)
        or getattr(usage, "input_token_count", None)
        or 0
    )
    output_tokens = int(
        getattr(usage, "candidates_token_count", None)
        or getattr(usage, "output_token_count", None)
        or 0
    )
    return input_tokens, output_tokens


def dry_run_critic(snapshot: dict[str, Any], *, model: str) -> CriticResult:
    """Deterministic template digest (no API call)."""
    errors = snapshot.get("errors") or []
    budget = snapshot.get("budget") or {}
    gemini_pct = budget.get("gemini_daily_pct")
    severity = "info"
    findings: list[dict[str, Any]] = [
        {
            "title": "Dry-run digest",
            "severity": "info",
            "category": "other",
            "evidence": "AGENTIC_PRO_DIGEST_DRY_RUN=1; no Gemini call made.",
            "suggested_action": "Disable dry-run to get a live Pro critique.",
        }
    ]
    if errors:
        severity = "warn"
        findings.append(
            {
                "title": f"{len(errors)} synthesized error signal(s)",
                "severity": "warn",
                "category": "workers",
                "evidence": str(errors[0].get("detail") or errors[0])[:300],
                "suggested_action": "Inspect failed/skipped jobs on the schedule panel.",
            }
        )
    budget_warning = None
    if isinstance(gemini_pct, (int, float)) and gemini_pct >= 80:
        severity = _max_severity(severity, "warn")
        budget_warning = f"Gemini daily usage at {gemini_pct}% of cap."
        findings.append(
            {
                "title": "Gemini budget elevated",
                "severity": "warn",
                "category": "budget",
                "evidence": budget_warning,
                "suggested_action": "Review feedback + digest spend or raise caps carefully.",
            }
        )
    summary = (
        f"**Dry-run** workflow digest (`{model}`). "
        f"Severity **{severity}** with {len(findings)} finding(s)."
    )
    payload = {
        "severity": severity,
        "summary_markdown": summary,
        "findings": findings,
        "budget_warning": budget_warning,
        "dry_run": True,
    }
    return CriticResult(
        severity=severity,
        summary_markdown=summary,
        findings=findings,
        budget_warning=budget_warning,
        payload=payload,
        model=model,
        cost_usd=0.0,
    )


def run_critic(
    snapshot: dict[str, Any],
    settings: Settings,
) -> CriticResult:
    """Call Gemini Pro with the snapshot; return structured critic result."""
    model = settings.agentic_pro_digest_model
    if settings.agentic_pro_digest_dry_run:
        return dry_run_critic(snapshot, model=model)

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set (required for Pro digest).")

    client = genai.Client(api_key=settings.gemini_api_key)
    user_prompt = (
        "Ops snapshot JSON follows. Produce the critique JSON.\n\n"
        + json.dumps(snapshot, default=str)
    )

    def _request() -> tuple[str, int, int]:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        text = _extract_response_text(response)
        in_tok, out_tok = _usage_tokens(response)
        return text, in_tok, out_tok

    raw_text, input_tokens, output_tokens = call_with_gemini_retry(
        _request, label="Agentic Pro digest"
    )
    result = parse_critic_response(raw_text, model=model)
    cost = cost_from_tokens(
        model, input_tokens=input_tokens, output_tokens=output_tokens
    )
    return CriticResult(
        severity=result.severity,
        summary_markdown=result.summary_markdown,
        findings=result.findings,
        budget_warning=result.budget_warning,
        payload={
            **result.payload,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            },
        },
        model=model,
        cost_usd=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
