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
from typing import Optional

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.paths import resolve_data_path, utc_artifact_stamp  # noqa: E402
from config.settings import GEMINI_MODEL, load_settings  # noqa: E402
from processors.post_analyser import PostAnalyser, verify_gemini_api  # noqa: E402
from processors.profile_sources import load_profile_lookup_from_post_scan  # noqa: E402
from storage.processed_store import ProcessedStore  # noqa: E402


# ── Pipeline log (session_state.terminal_log) ───────────────────────────────

class _SessionLogHandler(logging.Handler):
    """Forwards log records into st.session_state.terminal_log."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if "terminal_log" in st.session_state:
                _append_log(record.levelname, self.format(record))
        except Exception:  # noqa: BLE001
            pass


def _append_log(level: str, message: str) -> None:
    if "terminal_log" not in st.session_state:
        st.session_state.terminal_log = []
    st.session_state.terminal_log.append((level, message))


def _render_pipeline_log(*, expanded: bool = False) -> None:
    logs: list[tuple[str, str]] = st.session_state.get("terminal_log", [])
    if not logs:
        return
    with st.expander(f"Pipeline log ({len(logs)} line(s))", expanded=expanded):
        st.code("\n".join(f"{level:7}  {msg}" for level, msg in logs[-300:]), language="text")


_handler = _SessionLogHandler()
_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%H:%M:%S")
)
_pa_logger = logging.getLogger("processors.post_analyser")
if not any(isinstance(h, _SessionLogHandler) for h in _pa_logger.handlers):
    _pa_logger.addHandler(_handler)
    _pa_logger.setLevel(logging.DEBUG)
    _pa_logger.propagate = False


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


def _gemini_success_count(records: list[dict]) -> int:
    """Count posts where at least one Gemini field was populated."""
    return sum(
        1
        for record in records
        if any(record.get(key) is not None for key in ("hook_type", "tone", "topic", "has_explicit_cta", "writing_style"))
    )


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
if "profile_lookup" not in st.session_state:
    st.session_state.profile_lookup = {}
if "paired_profile_path" not in st.session_state:
    st.session_state.paired_profile_path = None
if "saved_analysis_paths" not in st.session_state:
    st.session_state.saved_analysis_paths = None

PROCESSED_DIR = resolve_data_path("data/processed")

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("1. Load a collection")
    data_dir = resolve_data_path(settings.raw_data_dir)
    post_scans = sorted(data_dir.glob("linkedin_*.json"), reverse=True) if data_dir.exists() else []
    post_scans = [f for f in post_scans if "profiles" not in f.name]

    posts: list[dict] = []
    profile_lookup: dict[str, dict] = {}
    if post_scans:
        selected_scan = st.selectbox(
            "Saved collections", ["-- Select --"] + [f.name for f in post_scans]
        )
        if selected_scan != "-- Select --":
            scan_path = data_dir / selected_scan
            posts = json.loads(scan_path.read_text())
            profile_lookup, paired_path = load_profile_lookup_from_post_scan(
                scan_path, settings.raw_data_dir
            )
            st.session_state.profile_lookup = profile_lookup
            st.session_state.paired_profile_path = str(paired_path) if paired_path else None
            st.info(f"{len(posts)} post(s) loaded.")
            if paired_path:
                st.caption(f"Paired profiles: `{paired_path.name}` ({len(profile_lookup)} authors).")
            else:
                st.caption("No paired profile data for this collection.")
    else:
        st.warning("No saved collections. Run Scraper Stage first.")

    st.markdown("---")
    st.header("2. Run analysis")
    st.caption(f"Gemini model: `{GEMINI_MODEL}`")
    if settings.gemini_api_key:
        st.caption("API key: configured")
    else:
        st.caption("API key: **not set**")
    if st.button("Test Gemini connection", disabled=not settings.gemini_api_key):
        with st.spinner("Probing Gemini..."):
            ok, message = verify_gemini_api(settings)
        if ok:
            st.success(message)
            _append_log("INFO", message)
        else:
            st.error(message)
            _append_log("ERROR", message)
    st.caption("Restart Streamlit after code changes (Ctrl+C, then re-run).")
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

    _render_pipeline_log(expanded=bool(st.session_state.get("terminal_log")))

# ── Run ───────────────────────────────────────────────────────────────────────

status = st.empty()

if run_python or run_full:
    st.session_state.terminal_log = []  # fresh log each run
    first_gemini_error: Optional[str] = None
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
                if gemini_records[-1].get("hook_type") is None and analyser.last_error:
                    _append_log("ERROR", analyser.last_error)
                    if first_gemini_error is None:
                        first_gemini_error = analyser.last_error
                progress.progress((i + 1) / len(subset), text=f"Stage 2: {i + 1}/{len(subset)}")

            ok = _gemini_success_count(gemini_records)
            if ok == 0:
                summary = (
                    f"Stage 2 complete but 0/{len(gemini_records)} posts returned Gemini features."
                )
                if first_gemini_error:
                    summary += f" First error: {first_gemini_error}"
                _append_log("ERROR", summary)
            elif ok < len(gemini_records):
                _append_log(
                    "WARNING",
                    f"Stage 2 partial success: {ok}/{len(gemini_records)} posts returned Gemini features.",
                )
            else:
                _append_log(
                    "INFO",
                    f"Stage 2 complete: {ok}/{len(gemini_records)} posts returned Gemini features.",
                )

        progress.empty()
        st.session_state.python_features = python_records
        st.session_state.gemini_features = gemini_records
        st.session_state.combined_records = _build_combined(
            python_records, gemini_records, st.session_state.profile_lookup
        )

        store = ProcessedStore(base_dir=str(PROCESSED_DIR))
        stamp = utc_artifact_stamp()
        save_label = "linkedin_analysed" if run_full else "linkedin_python"
        csv_path = store.save(save_label, st.session_state.combined_records, timestamp=stamp)
        jsonl_path = store.save_jsonl(
            save_label, st.session_state.combined_records, timestamp=stamp
        )
        st.session_state.saved_analysis_paths = {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "label": save_label,
        }
        _append_log("INFO", f"Saved CSV: {csv_path.name}")
        _append_log("INFO", f"Saved JSONL: {jsonl_path.name}")

        if run_full:
            ok = _gemini_success_count(gemini_records)
            if ok == 0:
                detail = first_gemini_error or "See Pipeline log in the sidebar."
                status.error(
                    f"Stage 1 done, but Gemini returned no features for any of "
                    f"{len(gemini_records)} post(s). {detail}"
                )
            elif ok < len(gemini_records):
                status.warning(
                    f"Done — {len(python_records)} post(s) analysed. "
                    f"Gemini features for {ok}/{len(gemini_records)} post(s)."
                )
            else:
                status.success(
                    f"Done — {len(python_records)} post(s) analysed with Gemini features. "
                    f"Saved `{csv_path.name}` + `{jsonl_path.name}`."
                )
        else:
            status.success(
                f"Done — {len(python_records)} post(s) analysed. "
                f"Saved `{csv_path.name}` + `{jsonl_path.name}`."
            )

    except Exception as exc:
        _append_log("ERROR", f"Pipeline exception: {type(exc).__name__}: {exc}")
        status.error(f"Analysis failed: {exc}")

_render_pipeline_log(
    expanded=bool(st.session_state.get("terminal_log"))
    and any(level == "ERROR" for level, _ in st.session_state.get("terminal_log", []))
)

# ── Output A: Python features ─────────────────────────────────────────────────

if st.session_state.python_features:
    st.subheader("Output A — Python Features (Stage 1)")
    st.caption("Derived from raw JSON — no AI, no cost.")
    st.dataframe(_strip_join_keys(st.session_state.python_features), use_container_width=True)

# ── Output B: Gemini features ─────────────────────────────────────────────────

if st.session_state.gemini_features:
    st.subheader("Output B — Gemini Features (Stage 2)")
    st.caption("One API call per post — qualitative signals only.")
    ok = _gemini_success_count(st.session_state.gemini_features)
    total = len(st.session_state.gemini_features)
    if ok == 0:
        st.error(
            "All Gemini fields are empty. Use **Test Gemini connection** in the sidebar "
            "and check **Pipeline log** for the exact API error."
        )
    elif ok < total:
        st.warning(f"Partial Gemini results: {ok}/{total} posts have features.")
    st.dataframe(st.session_state.gemini_features, use_container_width=True)

# ── Combined ──────────────────────────────────────────────────────────────────

if st.session_state.combined_records:
    has_profiles = st.session_state.profile_lookup and any(
        r.get("author_followers") is not None for r in st.session_state.combined_records
    )
    label = "Stage 1 + Stage 2" + (" + author profile enrichment" if has_profiles else "")
    st.subheader("Combined — All Features Merged")
    saved = st.session_state.get("saved_analysis_paths")
    if saved:
        st.caption(
            f"{label}. Saved to `data/processed/` as "
            f"`{Path(saved['csv']).name}` and `{Path(saved['jsonl']).name}`."
        )
    else:
        st.caption(label + ". Saved to data/processed/")
    st.dataframe(_strip_join_keys(st.session_state.combined_records), use_container_width=True)

