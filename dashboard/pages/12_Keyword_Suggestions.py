"""Suggest corpus search keywords from a LinkedIn profile or post URL.

Paste a URL → Apify scrape → Gemini → 10 keywords. Copy them into
Collect samples (or Agentic seeds) yourself — this page does not hand off.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import GEMINI_MODEL, load_settings  # noqa: E402
from dashboard.chrome import page_header, section_header  # noqa: E402
from telemetry.apify_ui import render_apify_cost_history, render_apify_session_cost  # noqa: E402


def _keyword_suggestions_mod():
    """Reload so a long-lived Streamlit process picks up classifier/scrape fixes."""
    import importlib

    import processors.keyword_suggestions as mod

    return importlib.reload(mod)


_ks = _keyword_suggestions_mod()
classify_linkedin_url = _ks.classify_linkedin_url
run_keyword_suggestions = _ks.run_keyword_suggestions

page_header(
    "Keyword suggestions",
    "Scrape a LinkedIn profile, company page, or post, then ask Gemini for "
    "10 search keywords — ready to paste into Collect samples.",
    step_hint="Optional helper · Copy keywords into Collect samples yourself",
)

section_header(
    "What this page does",
    """
**Input:** one LinkedIn personal profile (`/in/...`), **company page**
(`/company/...`), or post URL.

**Output:** exactly **10** search keywords (one per line). Copy them into
**Collect samples** or Agentic seed terms — nothing is auto-wired.

Uses Apify (profile or post-URL scraper) + Gemini. Company pages pull recent
company posts for context. Every run is logged under
`data/telemetry/keyword_suggestions.jsonl` and a full artifact is saved in
`data/processed/`.
""",
)

settings = load_settings()

if "keyword_suggestion_apify_runs" not in st.session_state:
    st.session_state.keyword_suggestion_apify_runs = []

missing = []
if not settings.apify_api_token:
    missing.append("APIFY_API_TOKEN")
if not settings.gemini_api_key:
    missing.append("GEMINI_API_KEY")
if missing:
    st.error(f"Missing env: {', '.join(missing)}. Check your `.env`.")

url = st.text_input(
    "LinkedIn profile, company, or post URL",
    placeholder="https://www.linkedin.com/in/...  or  /company/...  or  /posts/...",
    help="Personal profiles, company pages, and post URLs are supported.",
)

detected = classify_linkedin_url(url) if url.strip() else None
if detected == "profile":
    st.caption(f"Detected: **personal profile** scrape · Gemini model `{GEMINI_MODEL}`")
elif detected == "company":
    st.caption(
        f"Detected: **company page** (recent posts) · Gemini model `{GEMINI_MODEL}`"
    )
elif detected == "post":
    st.caption(f"Detected: **post** scrape · Gemini model `{GEMINI_MODEL}`")
elif url.strip():
    st.warning(
        "URL not recognised as a LinkedIn `/in/` profile, `/company/` page, "
        "or post (`/posts/`, `/feed/update/`, `/activity/`)."
    )

can_run = bool(
    url.strip()
    and detected in ("profile", "post", "company")
    and settings.apify_api_token
    and settings.gemini_api_key
)

if st.button("Scrape and suggest keywords", type="primary", disabled=not can_run):
    with st.spinner("Scraping LinkedIn, then asking Gemini for 10 keywords…"):
        result = run_keyword_suggestions(url.strip(), settings=settings)
    st.session_state["keyword_suggestion_result"] = result
    st.session_state.keyword_suggestion_apify_runs = list(result.apify_runs)

result = st.session_state.get("keyword_suggestion_result")
if result is not None:
    if result.error and not result.keywords:
        st.error(result.error)
    elif result.error:
        st.warning(result.error)

    if result.keywords:
        section_header(
            "Keywords (copy these)",
            "One per line — paste into Collect samples search, or Agentic seed terms.",
        )
        keywords_text = result.keywords_text()
        st.code(keywords_text, language=None)
        st.text_area(
            "Editable copy box",
            value=keywords_text,
            height=220,
            key="keyword_copy_box",
            help="Select all and copy, or edit before pasting elsewhere.",
        )
        st.caption(
            f"{len(result.keywords)} keywords · Gemini "
            f"`{result.gemini_model}` · "
            f"~${result.gemini_cost_usd:.6f} "
            f"({result.gemini_input_tokens}+{result.gemini_output_tokens} tokens)"
        )

    with st.expander("Scraped context sent to Gemini", expanded=False):
        st.json(result.context_summary or {})

    with st.expander("Run log", expanded=False):
        st.json(
            {
                "url": result.url,
                "url_kind": result.url_kind,
                "scrape_item_count": result.scrape_item_count,
                "apify_run_ids": result.apify_run_ids,
                "artifact_path": result.artifact_path,
                "log_path": result.log_path,
                "error": result.error,
                "recorded_at": result.recorded_at,
            }
        )
        if result.artifact_path:
            st.caption(f"Full scrape + keywords artifact: `{result.artifact_path}`")
        if result.log_path:
            st.caption(f"JSONL log: `{result.log_path}`")

st.divider()
render_apify_session_cost(st.session_state.keyword_suggestion_apify_runs)
render_apify_cost_history(settings)
