"""Throwaway visual test harness for the post-analysis pipeline (Step 2).

Takes a saved post scan, runs the two-stage feature extraction, optionally
merges author profile data, then shows three sections:
  - Output A: Python features  (instant, no AI cost)
  - Output B: Gemini features  (one API call per post)
  - Combined: A + B + essential author profile fields merged in

Not the product UI — exists purely to validate the processor produces
sensible output before we build the correlation layer on top.
"""

import json
import logging
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from processors.post_analyser import PostAnalyser  # noqa: E402
from storage.processed_store import ProcessedStore  # noqa: E402


# ── Floating terminal log handler ─────────────────────────────────────────────

class _SessionLogHandler(logging.Handler):
    """Forwards log records into st.session_state.terminal_log."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if "terminal_log" in st.session_state:
                level = record.levelname  # INFO / ERROR / WARNING
                msg = self.format(record)
                st.session_state.terminal_log.append((level, msg))
        except Exception:  # noqa: BLE001
            pass


_handler = _SessionLogHandler()
_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S")
)
_pa_logger = logging.getLogger("processors.post_analyser")
if not any(isinstance(h, _SessionLogHandler) for h in _pa_logger.handlers):
    _pa_logger.addHandler(_handler)
    _pa_logger.setLevel(logging.DEBUG)


def _render_floating_terminal() -> None:
    """Inject a fixed-position floating terminal panel at bottom-left."""
    logs: list[tuple[str, str]] = st.session_state.get("terminal_log", [])
    lines_html = ""
    for level, msg in logs[-300:]:
        css_class = "ok" if level == "INFO" else ("err" if level == "ERROR" else "warn")
        # escape for HTML
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines_html += f'<div class="tline {css_class}">{safe}</div>\n'
    if not lines_html:
        lines_html = '<div class="tline info">No output yet — run analysis to see logs.</div>'

    st.markdown(
        f"""
        <style>
        #ft-wrap {{
            position: fixed;
            bottom: 18px;
            right: 18px;
            z-index: 99999;
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
        }}
        #ft-toggle {{
            display: none;
        }}
        #ft-btn {{
            background: #111827;
            color: #34d399;
            border: 1px solid #34d399;
            border-radius: 6px;
            padding: 5px 14px;
            font-size: 12px;
            cursor: pointer;
            font-family: inherit;
            letter-spacing: 0.04em;
            display: inline-block;
            user-select: none;
        }}
        #ft-btn:hover {{ background: #064e3b; }}
        #ft-panel {{
            display: none;
            background: #0a0f1e;
            border: 1px solid #34d399;
            border-radius: 6px;
            margin-bottom: 6px;
            width: 620px;
            max-height: 300px;
            overflow-y: auto;
            padding: 10px 14px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.6);
        }}
        #ft-toggle:checked ~ #ft-panel {{
            display: block;
        }}
        #ft-toggle:checked ~ #ft-btn::before {{
            content: "▾ ";
        }}
        #ft-toggle:not(:checked) ~ #ft-btn::before {{
            content: "▸ ";
        }}
        .tline {{
            color: #9ca3af;
            font-size: 11px;
            line-height: 1.55;
            white-space: pre-wrap;
            word-break: break-all;
        }}
        .tline.ok   {{ color: #34d399; }}
        .tline.err  {{ color: #f87171; }}
        .tline.warn {{ color: #fbbf24; }}
        .tline.info {{ color: #60a5fa; }}
        </style>
        <div id="ft-wrap">
            <input type="checkbox" id="ft-toggle">
            <div id="ft-panel">
                {lines_html}
            </div>
            <label for="ft-toggle" id="ft-btn">Terminal</label>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _load_profile_lookup(path: Path) -> dict[str, dict]:
    """Build a publicIdentifier → essential fields map from a profile scan."""
    lookup: dict[str, dict] = {}
    for p in json.loads(path.read_text()):
        pid = p.get("publicIdentifier")
        if pid:
            lookup[pid] = {
                "author_followers": (
                    p.get("followersCount")
                    or p.get("followerCount")
                    or p.get("connectionsCount")
                ),
                "author_industry": p.get("industryName"),
                "author_company": p.get("companyName"),
            }
    return lookup


def _build_combined(
    python_records: list[dict],
    gemini_records: list[dict],
    profile_lookup: dict[str, dict],
) -> list[dict]:
    combined = []
    for i, pf in enumerate(python_records):
        record = dict(pf)
        if i < len(gemini_records):
            record.update(gemini_records[i])
        pid = pf.get("author_public_id", "")
        if pid and pid in profile_lookup:
            record.update(profile_lookup[pid])
        combined.append(record)
    return combined


def _strip_join_keys(records: list[dict]) -> list[dict]:
    """Remove internal join-key columns from display tables."""
    skip = {"post_id", "author_public_id", "linkedin_url"}
    return [{k: v for k, v in r.items() if k not in skip} for r in records]


# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Post Analysis Test Harness", layout="wide")
st.title("Step 2: Make Sense of Samples — Analysis Pipeline")
st.caption("Throwaway visual tool for testing the analysis pipeline. Not the product UI.")

settings = load_settings()

if "python_features" not in st.session_state:
    st.session_state.python_features = []
if "gemini_features" not in st.session_state:
    st.session_state.gemini_features = []
if "combined_records" not in st.session_state:
    st.session_state.combined_records = []
if "terminal_log" not in st.session_state:
    st.session_state.terminal_log = []

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("1. Load a post scan")
    data_dir = Path(settings.raw_data_dir)
    post_scans = sorted(data_dir.glob("linkedin_*.json"), reverse=True) if data_dir.exists() else []
    post_scans = [f for f in post_scans if "profiles" not in f.name]

    posts: list[dict] = []
    if post_scans:
        selected_scan = st.selectbox("Saved post scans", ["-- Select --"] + [f.name for f in post_scans])
        if selected_scan != "-- Select --":
            posts = json.loads((data_dir / selected_scan).read_text())
            st.info(f"{len(posts)} post(s) loaded.")
    else:
        st.warning("No saved post scans. Run Step 1 first.")

    st.markdown("---")
    st.header("2. Load profile data (optional)")
    st.caption("Adds follower count + industry to the combined view.")
    profile_scans = sorted(data_dir.glob("linkedin_profiles_*.json"), reverse=True) if data_dir.exists() else []

    profile_lookup: dict[str, dict] = {}
    if profile_scans:
        selected_profile = st.selectbox(
            "Saved profile scans", ["-- None --"] + [f.name for f in profile_scans]
        )
        if selected_profile != "-- None --":
            profile_lookup = _load_profile_lookup(data_dir / selected_profile)
            st.info(f"{len(profile_lookup)} author profile(s) loaded.")
    else:
        st.info("No saved profile scans found.")

    st.markdown("---")
    st.header("3. Run analysis")
    max_posts = st.number_input(
        "Max posts to analyse",
        min_value=1,
        value=len(posts) if posts else 1,
        help="Limits Gemini calls. Stage 1 is always instant.",
    )
    run_python = st.button("▶ Stage 1 only (Python, free)", disabled=not posts)
    run_full = st.button(
        "▶ Stage 1 + 2 (Python + Gemini)",
        disabled=not posts or not settings.gemini_api_key,
    )
    if not settings.gemini_api_key:
        st.caption("⚠️ GEMINI_API_KEY not set — Stage 2 disabled.")

# ── Run ───────────────────────────────────────────────────────────────────────

status = st.empty()

if run_python or run_full:
    st.session_state.terminal_log = []  # fresh log each run
    try:
        analyser = PostAnalyser(settings)
        subset = posts[: int(max_posts)]
        python_records: list[dict] = []
        gemini_records: list[dict] = []

        progress = st.progress(0, text="Stage 1 — Python features...")
        for i, post in enumerate(subset):
            python_records.append(analyser.compute_python_features(post))
            progress.progress((i + 1) / len(subset), text=f"Stage 1: {i + 1}/{len(subset)}")

        if run_full:
            progress.progress(0, text="Stage 2 — Gemini features...")
            for i, (post, pf) in enumerate(zip(subset, python_records)):
                gemini_records.append(analyser.compute_gemini_features(post, pf))
                progress.progress((i + 1) / len(subset), text=f"Stage 2: {i + 1}/{len(subset)}")

        progress.empty()
        st.session_state.python_features = python_records
        st.session_state.gemini_features = gemini_records
        st.session_state.combined_records = _build_combined(
            python_records, gemini_records, profile_lookup
        )

        # Persist the combined result (falls back to python-only if no Gemini)
        ProcessedStore().save("linkedin", st.session_state.combined_records)
        status.success(f"Done — {len(python_records)} post(s) analysed.")

    except Exception as exc:
        _pa_logger.error("Pipeline exception: %s: %s", type(exc).__name__, exc)
        status.error(f"Analysis failed: {exc}")

# ── Output A: Python features ─────────────────────────────────────────────────

if st.session_state.python_features:
    st.subheader("Output A — Python Features (Stage 1)")
    st.caption("Derived from raw JSON — no AI, no cost.")
    st.dataframe(_strip_join_keys(st.session_state.python_features), use_container_width=True)

# ── Output B: Gemini features ─────────────────────────────────────────────────

if st.session_state.gemini_features:
    st.subheader("Output B — Gemini Features (Stage 2)")
    st.caption("One API call per post — qualitative signals only.")
    st.dataframe(st.session_state.gemini_features, use_container_width=True)

# ── Combined ──────────────────────────────────────────────────────────────────

if st.session_state.combined_records:
    has_profiles = profile_lookup and any(
        r.get("author_followers") is not None for r in st.session_state.combined_records
    )
    label = "Stage 1 + Stage 2" + (" + author profile enrichment" if has_profiles else "")
    st.subheader("Combined — All Features Merged")
    st.caption(label + ". Saved to data/processed/")
    st.dataframe(_strip_join_keys(st.session_state.combined_records), use_container_width=True)

# ── Floating terminal (always rendered) ──────────────────────────────────────

_render_floating_terminal()

