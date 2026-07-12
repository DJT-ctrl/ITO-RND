"""Throwaway visual test harness for Step 4 — RAG Retrieval Endpoint (T2).

Exercises the exact same code path as the FastAPI endpoint
(POST /api/v1/similar-posts in api/main.py) directly — embed_query()
(processors/embedder.py) + find_similar() (storage/vector_store.py) — so
this page works without needing `uvicorn` running separately, the same way
dashboard/pages/5_Vectorisation.py calls embed_batch()/save_embeddings()
directly rather than going through an HTTP layer.

What this visualises:
  - A draft post's embedding (task_type="RETRIEVAL_QUERY") compared against
    the 250 already-ingested posts via pgvector cosine distance.
  - The exact JSON shape the real API endpoint returns (T2.3's contract).
  - Timing broken into the Gemini embedding call vs. the SQL query alone —
    Erdal's T2.2 "under 150ms" success criterion applies to the SQL step
    only (already proven at ~2-4ms; the Gemini call is a separate, external
    network cost, see PhaseT2plan.md Decision #2).

Not the product UI — exists purely to validate T2's retrieval endpoint the
same way earlier pages validate their pipeline stage.
"""

import sys
import time
from pathlib import Path

import streamlit as st
from pgvector.psycopg import register_vector

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from config.settings import load_settings  # noqa: E402
from dashboard.pipeline_ui import render_corpus_sidebar  # noqa: E402
from processors.embedder import embed_query  # noqa: E402
from storage.vector_store import find_similar, get_connection  # noqa: E402

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Similarity Search Test Harness", layout="wide")
st.title("Step 4: Similar Posts — RAG Retrieval (T2)")
st.caption(
    "Throwaway visual tool for the T2 retrieval endpoint. Calls the real "
    "Gemini embedding endpoint (task_type=RETRIEVAL_QUERY) and the real "
    "Postgres+pgvector `posts` table — same code path as "
    "`POST /api/v1/similar-posts` in api/main.py."
)

settings = load_settings()

if "similar_result" not in st.session_state:
    st.session_state.similar_result = None

missing_config = []
if not settings.gemini_api_key:
    missing_config.append("GEMINI_API_KEY")
if not settings.database_url:
    missing_config.append("DATABASE_URL")

with st.sidebar:
    render_corpus_sidebar(settings)
    st.markdown("---")
    st.header("Query")
    draft_content = st.text_area(
        "Draft post text",
        value="Excited to announce our new backend engineering hire!",
        height=160,
        help="The text you're drafting — this gets embedded and compared "
        "against historical posts.",
    )
    limit = st.slider("Number of similar posts to return", min_value=1, max_value=50, value=10)
    user_id = st.text_input(
        "Subscriber user_id (optional)",
        value="",
        help="When set, retrieval is scoped to this subscriber's own posts first, falling back "
        "to the global corpus automatically if they don't have enough of their own yet.",
    ).strip() or None
    run_clicked = st.button(
        "\u25b6 Find similar posts",
        type="primary",
        disabled=bool(missing_config) or not draft_content.strip(),
    )
    if missing_config:
        st.caption(f"\u26a0\ufe0f Missing config: {', '.join(missing_config)} — check your .env file.")

# ── Run ────────────────────────────────────────────────────────────────────────

status = st.empty()

if run_clicked:
    try:
        status.info("Embedding draft text via Gemini (task_type=RETRIEVAL_QUERY)...")
        embed_start = time.perf_counter()
        query_vector, _prompt_tokens = embed_query(draft_content, settings)
        embed_ms = (time.perf_counter() - embed_start) * 1000

        status.info("Running cosine-distance query against the posts table...")
        conn = get_connection(settings)
        try:
            register_vector(conn)
            sql_start = time.perf_counter()
            rows = find_similar(conn, query_vector, limit=limit, user_id=user_id)
            sql_ms = (time.perf_counter() - sql_start) * 1000
        finally:
            conn.close()

        st.session_state.similar_result = {
            "query_content": draft_content,
            "rows": rows,
            "embed_ms": embed_ms,
            "sql_ms": sql_ms,
            "vector_norm": float((query_vector**2).sum() ** 0.5),
        }
        status.success(f"Done. Found {len(rows)} similar post(s).")
    except Exception as exc:  # surfaced in the UI on purpose for a test harness
        status.error(f"Similarity search failed: {exc}")

# ── Result ───────────────────────────────────────────────────────────────────

if st.session_state.similar_result:
    result = st.session_state.similar_result
    rows = result["rows"]

    st.markdown("---")
    st.subheader("Timing (Erdal's T2.2 success criterion: SQL step under 150ms)")
    col1, col2, col3 = st.columns(3)
    col1.metric("Gemini embed call", f"{result['embed_ms']:.0f} ms")
    col2.metric("SQL cosine query", f"{result['sql_ms']:.2f} ms")
    col3.metric("Query vector norm", f"{result['vector_norm']:.3f}")
    if result["sql_ms"] < 150:
        st.caption("\u2705 SQL query is well under the 150ms budget.")
    else:
        st.caption("\u26a0\ufe0f SQL query exceeded the 150ms budget.")

    st.subheader(f"Top {len(rows)} similar posts (nearest-first)")
    if rows:
        st.dataframe(
            [
                {
                    "post_id": r["post_id"],
                    "cosine_distance": round(r["cosine_distance"], 4),
                    "likes": r["likes"],
                    "comments": r["comments"],
                    "shares": r["shares"],
                    "total_engagement": r["total_engagement"],
                    "engagement_percentile": r["engagement_percentile"],
                    "content_preview": (r["content"][:120] + "\u2026") if len(r["content"]) > 120 else r["content"],
                }
                for r in rows
            ],
            use_container_width=True,
        )
    else:
        st.info("No posts found — has the database been ingested? (`python -m processors.run_db_ingest`)")

    st.subheader("Raw API response shape (matches SimilarPostsResponse in api/schemas.py)")
    st.json(
        {
            "query_content": result["query_content"],
            "results": rows[:3],
        }
    )
