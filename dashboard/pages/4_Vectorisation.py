"""Throwaway visual test harness for Step 3 — Vector Embedding Generation (T1.3).

Loads one or more analysed pipeline bundles, re-joins raw post text scoped to
each bundle's source scraper file(s), and runs a *manual, cost-controlled*
batch through the real Gemini embedding endpoint (processors/embedder.py).

Not the product UI — exists purely to validate T1.3's output before T1.5
(pgvector insertion) is built on top of it.
"""

import sys
from pathlib import Path

import numpy as np
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.paths import resolve_data_path  # noqa: E402
from config.settings import load_settings  # noqa: E402
from dashboard.chrome import page_header, pipeline_flow_strip, section_header  # noqa: E402
from dashboard.pipeline_readiness import compute_corpus_readiness  # noqa: E402
from dashboard.pipeline_ui import (  # noqa: E402
    analysed_filenames_for_bundles,
    render_bundle_multiselect,
)
from processors.embedder import embed_batch, save_embeddings  # noqa: E402
from processors.run_embeddings import load_and_join  # noqa: E402
from storage.pipeline_registry import register_embeddings_bundle  # noqa: E402

_MIN_WORD_COUNT = 10

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Make embeddings", layout="wide")
settings = load_settings()
_corpus_ready = compute_corpus_readiness("embed", settings=settings)
page_header(
    "Make embeddings",
    "Turn analysed post text into vectors (Gemini embeddings) so we can find "
    "similar posts later. This is paid and rate-limited — use the sidebar batch "
    "size to stay in control.",
    step_hint="Corpus step 4 of 5 · Previous: Find patterns · Next: Search similar",
)
pipeline_flow_strip("corpus", "embed", readiness=_corpus_ready)
_search_cue = _corpus_ready.steps.get("search")
if _search_cue and _search_cue.state == "ready":
    st.caption(f"→ {_search_cue.hint}")
elif _corpus_ready.steps.get("embed") and _corpus_ready.steps["embed"].state == "ready":
    st.caption(f"→ {_corpus_ready.steps['embed'].hint}")

section_header(
    "What this page does",
    """
Select analysed bundle(s) from **Analyse posts**. We re-join raw text from those
bundles' scraper files, embed a **manual batch**, and save `.npy` + registry
metadata for ingest / similarity search.
""",
)

if "embed_result" not in st.session_state:
    st.session_state.embed_result = None

# ── Sidebar: pick bundle(s) + manual controls ─────────────────────────────────

with st.sidebar:
    st.header("1. Load analysed bundle(s)")
    selected_bundles = render_bundle_multiselect(
        label="Pipeline bundles (Stage 1 + 2)",
        min_stage="analysed",
        key="vector_bundles",
        require_gemini=True,
    )

    joined_records: list[dict] = []
    jsonl_names: list[str] = []
    if selected_bundles:
        jsonl_names = analysed_filenames_for_bundles(selected_bundles)
        processed_dir = resolve_data_path("data/processed")
        try:
            paths = [str(processed_dir / name) for name in jsonl_names]
            joined_records, _, source_scans = load_and_join(
                settings=settings, processed_files=paths
            )
            st.info(f"{len(joined_records)} post(s) loaded and joined with raw text.")
            st.caption(f"Source scraper files: {', '.join(source_scans) or 'all raw (legacy)'}")
        except ValueError as exc:
            st.error(str(exc))

    eligible = [
        r for r in joined_records
        if (r.get("content") or "").strip() and r.get("word_count", 0) >= _MIN_WORD_COUNT
    ]

    st.markdown("---")
    st.header("2. Manual controls")
    st.caption(
        f"{len(eligible)} of {len(joined_records)} loaded post(s) are eligible "
        f"(word_count \u2265 {_MIN_WORD_COUNT}, non-blank content). Ineligible posts are always skipped."
    )
    max_posts = st.number_input(
        "Max posts to embed this run",
        min_value=1,
        value=len(eligible) if eligible else 1,
        help="Keep this small for a test run — each post costs a Gemini embedding API call.",
    )
    run_clicked = st.button(
        "\u25b6 Run embedding batch",
        type="primary",
        disabled=not eligible or not settings.gemini_api_key,
    )
    if not settings.gemini_api_key:
        st.caption("\u26a0\ufe0f GEMINI_API_KEY not set — embedding disabled.")

# ── Run ────────────────────────────────────────────────────────────────────────

status = st.empty()

if run_clicked and selected_bundles:
    try:
        subset = eligible[: int(max_posts)]
        status.info(f"Embedding {len(subset)} post(s) via Gemini (gemini-embedding-001, 3072-dim)...")
        vectors, skipped = embed_batch(subset, settings)
        out_path = save_embeddings(vectors, "linkedin")
        primary_bundle = selected_bundles[0]
        register_embeddings_bundle(
            bundle_id=primary_bundle.bundle_id,
            embeddings_npy=str(out_path),
            embedding_post_ids=[r["post_id"] for r in subset],
            source_jsonl=jsonl_names[0],
        )
        st.session_state.embed_result = {
            "vectors": vectors,
            "skipped": skipped,
            "out_path": out_path,
            "source_files": jsonl_names,
            "bundle_ids": [b.bundle_id for b in selected_bundles],
            "post_ids": [r["post_id"] for r in subset],
        }
        status.success(f"Done. Embedded {len(vectors)} post(s) \u2192 `{out_path}`")
    except Exception as exc:  # surfaced in the UI on purpose for a test harness
        status.error(f"Embedding failed: {exc}")

# ── Run result + sanity checks ─────────────────────────────────────────────────

if st.session_state.embed_result:
    result = st.session_state.embed_result
    vectors: np.ndarray = result["vectors"]

    st.markdown("---")
    st.subheader("Run result")
    col1, col2, col3 = st.columns(3)
    col1.metric("Vectors produced", vectors.shape[0])
    col2.metric("Dimensions", vectors.shape[1] if vectors.ndim == 2 and vectors.shape[0] else 0)
    col3.metric("Skipped (short/blank)", result["skipped"])
    st.write(f"Saved to `{result['out_path']}`")
    st.write(f"Source bundle(s): `{', '.join(result.get('bundle_ids', []))}`")
    st.write(f"Source dataset(s): `{', '.join(result.get('source_files', []))}`")

    if vectors.shape[0] > 0:
        norms = np.linalg.norm(vectors, axis=1)
        st.write("**Sanity checks** (a broken embedding is usually all-zeros -> norm 0, or contains NaN):")
        st.dataframe(
            {
                "post_id": result["post_ids"],
                "vector_norm": norms.round(4),
                "has_nan": np.isnan(vectors).any(axis=1),
                "first_5_values": [v[:5].round(4).tolist() for v in vectors],
            },
            use_container_width=True,
        )

        if vectors.shape[0] >= 2:
            st.write("**Cosine similarity matrix** — semantically similar posts should score higher:")
            normed = vectors / norms[:, None]
            sim_matrix = normed @ normed.T
            st.dataframe(
                sim_matrix.round(3),
                use_container_width=True,
            )

# ── Inspect a previously saved embeddings file ─────────────────────────────────

st.markdown("---")
st.subheader("Inspect a saved embeddings file")
st.caption("Loads any data/embeddings/*.npy produced by a previous run.")

embeddings_dir = resolve_data_path("data/embeddings")
embedding_files = sorted(embeddings_dir.glob("*.npy"), reverse=True) if embeddings_dir.exists() else []

if embedding_files:
    selected_embedding = st.selectbox(
        "Saved .npy files", ["-- Select --"] + [f.name for f in embedding_files], key="inspect_select"
    )
    if selected_embedding != "-- Select --":
        loaded = np.load(embeddings_dir / selected_embedding)
        st.write(f"Shape: `{loaded.shape}` — dtype: `{loaded.dtype}`")
        if loaded.shape[0] > 0:
            norms = np.linalg.norm(loaded, axis=1)
            st.write(f"Vector norm range: {norms.min():.3f} – {norms.max():.3f}")
            st.write(f"Any NaN values: {bool(np.isnan(loaded).any())}")
            st.write(f"Any all-zero vectors (broken embeddings): {bool((norms == 0).any())}")
        else:
            st.info("This file has 0 vectors (every post in that run was skipped).")
else:
    st.info("No saved embeddings yet. Run a batch above first.")
