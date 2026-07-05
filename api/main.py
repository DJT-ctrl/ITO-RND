"""FastAPI app (T2.1/T2.2): a health check + the cosine-similarity retrieval
endpoint.

Handler flow for POST /api/v1/similar-posts:
  1. embed_query(content, settings)  — embed the incoming draft text
     (task_type="RETRIEVAL_QUERY", see processors/embedder.py).
  2. find_similar(conn, vector, limit) — cosine-distance nearest-neighbour
     lookup against the halfvec(3072) HNSW index (storage/vector_store.py).
  3. Wrap the returned rows into SimilarPost objects.

Settings are loaded once at module scope (same pattern every other entry
point in this repo uses). A fresh DB connection is opened per request —
simplest correct option for this phase's scale; a connection pool is a
legitimate future optimization but is scope creep for now (see
PhaseT2plan.md Decision #3).
"""

from fastapi import FastAPI, HTTPException
from pgvector.psycopg import register_vector

from agents.orchestrator import run_evaluation_cycle
from agents.schemas import PostEvaluationState
from api.schemas import EvaluateRequest, SimilarPost, SimilarPostsRequest, SimilarPostsResponse
from config.settings import load_settings
from processors.embedder import embed_query
from storage.vector_store import find_similar, get_connection

settings = load_settings()

app = FastAPI(title="ITO Post Similarity API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/similar-posts", response_model=SimilarPostsResponse)
def similar_posts(request: SimilarPostsRequest) -> SimilarPostsResponse:
    try:
        query_vector = embed_query(request.content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    conn = get_connection(settings)
    try:
        # get_connection() intentionally doesn't register the pgvector
        # adapter (see its docstring — the `vector` extension may not exist
        # on a brand-new database). Here, the schema is already assumed to
        # exist (this is a read-only query endpoint), so it's safe to
        # register the adapter immediately so `query_vector` (a numpy
        # array) can be passed directly as a query parameter.
        register_vector(conn)
        rows = find_similar(conn, query_vector, limit=request.limit)
    finally:
        conn.close()

    return SimilarPostsResponse(
        query_content=request.content,
        results=[SimilarPost(**row) for row in rows],
    )


@app.post("/api/v1/evaluate", response_model=PostEvaluationState)
async def evaluate(request: EvaluateRequest) -> PostEvaluationState:
    """T3.1: run the async evaluation cycle end-to-end over HTTP.

    No Predictor/Diagnostic agents are registered yet (T3.2/T3.3 don't exist
    yet), so `predictor_result`/`diagnostics`/`variants` will be empty on the
    response — that's expected. This endpoint's job right now is only to
    prove the orchestrator (agents/orchestrator.py) runs correctly end-to-end,
    including the neighbor-fetch stage which reuses embed_query()/find_similar().
    """
    try:
        return await run_evaluation_cycle(request.content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
