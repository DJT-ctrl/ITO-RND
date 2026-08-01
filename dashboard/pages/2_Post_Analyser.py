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
from dashboard.chrome import page_header, pipeline_flow_strip, section_header  # noqa: E402
from processors.corpus_benchmarks import build_snapshot, save_snapshot  # noqa: E402
from processors.dedup import dedupe_posts  # noqa: E402
from processors.finalize_records import analysed_dataset_label  # noqa: E402
from processors.post_analyser import (  # noqa: E402
    DEFAULT_GEMINI_WORKERS,
    PostAnalyser,
    map_gemini_features,
    verify_gemini_api,
)
from processors.profile_sources import load_profile_lookup_from_post_scan  # noqa: E402
from storage.pipeline_registry import register_analysed_bundle  # noqa: E402
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


def _persist_analysed_bundle(
    records: list[dict],
    *,
    with_gemini: bool,
    processed_dir: Path,
) -> tuple[list[dict], list[dict], Path, Path, Optional[Path]]:
    """Finalize, save CSV/JSONL, register manifest. Returns validated + paths.

    Always reloads ``finalize_records`` so a long-lived Streamlit process cannot
    keep a stale validator that rejects Gemini labels like ``quote``.
    """
    import importlib

    import processors.finalize_records as finalize_mod

    importlib.reload(finalize_mod)
    sanitize = finalize_mod.sanitize_gemini_fields
    finalize = finalize_mod.finalize_analysed_records
    label_fn = finalize_mod.analysed_dataset_label

    # Defense in depth: coerce Gemini enums before finalize, even if the
    # imported finalize helper is somehow stale.
    cleaned = [sanitize(dict(r)) for r in records]
    validated_records, flagged_records = finalize(cleaned)
    if not validated_records:
        raise ValueError(
            "Finalize produced 0 clean records "
            f"({len(flagged_records)} flagged). Nothing to save for Pattern Analysis."
        )
    store = ProcessedStore(base_dir=str(processed_dir))
    stamp = utc_artifact_stamp()
    save_label = label_fn(with_gemini=with_gemini)
    csv_path = store.save(save_label, validated_records, timestamp=stamp)
    jsonl_path = store.save_jsonl(save_label, validated_records, timestamp=stamp)
    flagged_path = None
    if flagged_records:
        flagged_path = store.save_jsonl(
            f"{save_label}_flagged", flagged_records, timestamp=stamp
        )
        _append_log(
            "WARNING",
            f"Held out {len(flagged_records)} post(s) with anomalous engagement "
            f"for review: {flagged_path.name}",
        )
    register_analysed_bundle(
        bundle_id=stamp,
        source_scans=st.session_state.get("source_scans", []),
        source_profiles=st.session_state.get("source_profiles", []),
        analysed_jsonl=jsonl_path.name,
        analysed_csv=csv_path.name,
        flagged_jsonl=flagged_path.name if flagged_path else None,
        with_gemini=with_gemini,
        post_count=len(validated_records),
    )
    try:
        snapshot = build_snapshot(validated_records)
        snapshot_path = save_snapshot(snapshot)
        _append_log("INFO", f"Corpus benchmarks for Pattern Analysis: {snapshot_path.name}")
    except ValueError:
        pass
    _append_log("INFO", f"Saved CSV: {csv_path.name}")
    _append_log("INFO", f"Saved JSONL: {jsonl_path.name}")
    _append_log(
        "INFO",
        f"finalize_records loaded from {finalize_mod.__file__} "
        f"(quote→{sanitize({'hook_type': 'quote'}).get('hook_type')})",
    )
    return validated_records, flagged_records, csv_path, jsonl_path, flagged_path


# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Analyse posts", layout="wide")
page_header(
    "Analyse posts",
    "Turn raw scraped JSON into structured features. "
    "**Stage 1** is free Python (fast). **Stage 2** calls Gemini per post "
    "(paid and slow) — keep “Max posts” small while testing.",
    step_hint="Corpus step 2 of 5 · Previous: Collect samples · Next: Find patterns",
)
pipeline_flow_strip("corpus", "analyse")

section_header(
    "How to test without burning budget",
    """
1. Load one saved collection from the sidebar.
2. Set **Max posts** low (e.g. 5–20) while iterating.
3. Prefer **Stage 1 only** until the free features look right.
4. Run **Stage 1 + 2** only when you need Gemini tags (hook type, etc.).

Stage 2 is the slow/expensive step — that is expected, not a UI bug.
""",
)

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
if "analysis_with_gemini" not in st.session_state:
    st.session_state.analysis_with_gemini = False
if "source_scans" not in st.session_state:
    st.session_state.source_scans = []
if "source_profiles" not in st.session_state:
    st.session_state.source_profiles = []

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
        scan_options = [f.name for f in post_scans]
        selected_scans = st.multiselect(
            "Saved collections (select one or more to combine)",
            scan_options,
            help="Posts from multiple collections are merged and deduplicated before analysis.",
        )
        if selected_scans:
            combined: list[dict] = []
            merged_profiles: dict[str, dict] = {}
            paired_names: list[str] = []
            for scan_name in selected_scans:
                scan_path = data_dir / scan_name
                combined.extend(json.loads(scan_path.read_text()))
                pl, paired_path = load_profile_lookup_from_post_scan(
                    scan_path, settings.raw_data_dir
                )
                merged_profiles.update(pl)
                if paired_path:
                    paired_names.append(paired_path.name)
            posts, dupes_removed = dedupe_posts(combined)
            profile_lookup = merged_profiles
            st.session_state.profile_lookup = profile_lookup
            st.session_state.source_scans = selected_scans
            st.session_state.source_profiles = paired_names
            st.session_state.paired_profile_path = paired_names[0] if paired_names else None
            st.info(f"{len(posts)} post(s) loaded from {len(selected_scans)} collection(s).")
            if dupes_removed:
                st.caption(f"Removed {dupes_removed} exact duplicate(s) across collections.")
            if paired_names:
                st.caption(f"Paired profiles: {', '.join(f'`{n}`' for n in paired_names)}.")
            else:
                st.caption("No paired profile data for these collections.")
    else:
        st.warning("No saved collections. Run **Collect samples** first.")

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
    default_max = min(10, len(posts)) if posts else 1
    max_posts = st.number_input(
        "Max posts to analyse (keep small for Stage 2 tests)",
        min_value=1,
        value=default_max,
        help=(
            "Caps how many posts run. Stage 1 is free/fast; Stage 2 = one "
            "Gemini call per post. Use a low number while testing."
        ),
    )
    gemini_workers = st.number_input(
        "Parallel Gemini calls",
        min_value=1,
        max_value=20,
        value=DEFAULT_GEMINI_WORKERS,
        help=(
            "How many Stage 2 Gemini requests to run at once. Same number of "
            "API calls (and cost) either way — only wall time changes. "
            "Use 1 to force sequential (old behaviour)."
        ),
    )
    run_python = st.button("▶ Stage 1 only (Python, free / fast)", disabled=not posts)
    run_full = st.button(
        "▶ Stage 1 + 2 (Python + Gemini — slow / paid)",
        disabled=not posts or not settings.gemini_api_key,
    )
    if not settings.gemini_api_key:
        st.caption("GEMINI_API_KEY not set — Stage 2 disabled.")

    _render_pipeline_log(expanded=bool(st.session_state.get("terminal_log")))

# ── Run ───────────────────────────────────────────────────────────────────────

status = st.empty()

if run_python or run_full:
    st.session_state.terminal_log = []  # fresh log each run
    # Mutable box — Streamlit pages run at module scope, so nested
    # callbacks cannot use ``nonlocal`` for a sibling assignment.
    first_gemini_error: list[Optional[str]] = [None]
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

            def _on_stage2_progress(done: int, total: int) -> None:
                progress.progress(done / total, text=f"Stage 2: {done}/{total}")

            def _on_stage2_error(message: str) -> None:
                _append_log("ERROR", message)
                if first_gemini_error[0] is None:
                    first_gemini_error[0] = message

            gemini_records = map_gemini_features(
                subset,
                python_records,
                settings,
                max_workers=int(gemini_workers),
                on_progress=_on_stage2_progress,
                on_error=_on_stage2_error,
            )

            ok = _gemini_success_count(gemini_records)
            if ok == 0:
                summary = (
                    f"Stage 2 complete but 0/{len(gemini_records)} posts returned Gemini features."
                )
                if first_gemini_error[0]:
                    summary += f" First error: {first_gemini_error[0]}"
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
        st.session_state.analysis_with_gemini = bool(run_full)
        st.session_state.combined_records = _build_combined(
            python_records, gemini_records, st.session_state.profile_lookup
        )
        # Clear saved paths until persist succeeds — if finalize/save fails,
        # recovery UI can re-save from session combined_records.
        st.session_state.saved_analysis_paths = None

        validated_records, flagged_records, csv_path, jsonl_path, _flagged = (
            _persist_analysed_bundle(
                st.session_state.combined_records,
                with_gemini=bool(run_full),
                processed_dir=PROCESSED_DIR,
            )
        )
        st.session_state.combined_records = validated_records
        st.session_state.saved_analysis_paths = {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "label": analysed_dataset_label(with_gemini=bool(run_full)),
        }

        if run_full:
            ok = _gemini_success_count(gemini_records)
            if ok == 0:
                detail = first_gemini_error[0] or "See Pipeline log in the sidebar."
                status.error(
                    f"Gemini returned no features for any of "
                    f"{len(gemini_records)} post(s). {detail} "
                    f"Bundle still saved as `{jsonl_path.name}` "
                    "(may have empty tags)."
                )
            elif ok < len(gemini_records):
                status.warning(
                    f"Done — {len(validated_records)} post(s) saved "
                    f"(`{jsonl_path.name}`). "
                    f"Gemini features for {ok}/{len(gemini_records)} post(s)."
                )
            else:
                status.success(
                    f"Done — {len(validated_records)} post(s) analysed with Gemini. "
                    f"Saved `{csv_path.name}` + `{jsonl_path.name}`."
                )
        else:
            status.success(
                f"Done — {len(validated_records)} post(s) analysed. "
                f"Saved `{csv_path.name}` + `{jsonl_path.name}`."
            )

    except Exception as exc:
        _append_log("ERROR", f"Pipeline exception: {type(exc).__name__}: {exc}")
        status.error(
            f"Analysis failed before save: {exc}. "
            "If Output tables below still show results, use "
            "**Save pending analysis to disk** to recover."
        )

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

pending_unsaved = (
    bool(st.session_state.combined_records)
    and not st.session_state.get("saved_analysis_paths")
)
if pending_unsaved:
    st.warning(
        f"**Unsaved analysis in this browser session:** "
        f"{len(st.session_state.combined_records)} post(s) are in memory but "
        "were not written to `data/processed/` / the pipeline manifest. "
        "Find patterns only lists saved Gemini bundles — click save below."
    )
    if st.button("Save pending analysis to disk", type="primary", key="save_pending_analysis"):
        try:
            with_gemini = bool(st.session_state.get("analysis_with_gemini")) or bool(
                st.session_state.gemini_features
            )
            validated_records, _, csv_path, jsonl_path, _ = _persist_analysed_bundle(
                st.session_state.combined_records,
                with_gemini=with_gemini,
                processed_dir=PROCESSED_DIR,
            )
            st.session_state.combined_records = validated_records
            st.session_state.analysis_with_gemini = with_gemini
            st.session_state.saved_analysis_paths = {
                "csv": str(csv_path),
                "jsonl": str(jsonl_path),
                "label": analysed_dataset_label(with_gemini=with_gemini),
            }
            st.success(
                f"Saved {len(validated_records)} post(s) → `{jsonl_path.name}`. "
                "Reload **Find patterns** to see the bundle."
            )
        except Exception as exc:
            _append_log("ERROR", f"Pending save failed: {type(exc).__name__}: {exc}")
            st.error(f"Could not save pending analysis: {exc}")

if st.session_state.combined_records:
    has_profiles = st.session_state.profile_lookup and any(
        r.get("author_followers") is not None
        or r.get("follower_count") is not None
        for r in st.session_state.combined_records
    )
    label = "Stage 1 + Stage 2" + (" + author profile enrichment" if has_profiles else "")
    st.subheader("Combined — All Features Merged")
    saved = st.session_state.get("saved_analysis_paths")
    if saved:
        st.caption(
            f"{label}. Saved to `data/processed/` as "
            f"`{Path(saved['csv']).name}` and `{Path(saved['jsonl']).name}` "
            f"({saved['label']}) — ready for Pattern Analysis and Vectorisation."
        )
    else:
        st.caption(label + ". Not saved to disk yet.")
    st.dataframe(_strip_join_keys(st.session_state.combined_records), use_container_width=True)

