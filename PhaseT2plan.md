# T2 Implementation Plan: FastAPI + Cosine-Similarity Retrieval Endpoint (Phase 2)

**Date:** 2026-07-05
**Status:** READY FOR IMPLEMENTATION (hand this file to a fresh chat/agent to execute)

**Erdal's spec (First Ideas/Erdals_plan_Phase2.md):**

| Task | Description | Success criteria | Tech stack |
|------|-------------|-------------------|------------|
| **T2.1** FastAPI Core Setup | Build a clean asynchronous FastAPI setup. Configure Nginx on the EC2 instance to forward web traffic to Uvicorn. | API container live on EC2 port 8000, responding to HTTP requests through an Nginx reverse proxy. | FastAPI / Uvicorn / Nginx |
| **T2.2** RAG Retrieval Endpoint | Implement direct SQL execution within FastAPI to fetch the 10 closest performance records using cosine distance. | API endpoint yields matching historical records with real performance counters in under 150ms. | FastAPI / SQL / pgvector |
| **T2.3** API Contract Definition | Standardize input/output JSON signatures so the frontend developer can mock client requests locally. | Complete OpenAPI specification (/docs) accessible from the EC2 server IP. | Pydantic / OpenAPI |

---

## Why this phase really is small

All the hard infrastructure work is already done:

- Postgres+pgvector is live (currently running locally via colima), with a `posts` table holding 250 posts,
  each with a `3072`-dim `embedding` column and an HNSW index (`posts_embedding_hnsw_idx`, indexed via a
  `halfvec(3072)` cast — see storage/schema.sql).
- The cosine-distance query itself was already proven in T1.4_DATABASE_PLAN.md at **1.9ms** — nowhere near
  the 150ms budget. T2.2's "under 150ms" is almost free.
- The only genuinely new pieces: (1) a thin FastAPI process, (2) one SQL query wrapped in a Python
  function, (3) embedding the *incoming* text at request time before comparing it.

The "cosine step" is literally one SQL clause:
```sql
ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072) LIMIT 10
```
`<=>` is pgvector's cosine-distance operator. Everything else in this phase is plumbing around that line.

---

## Current local environment (context for whoever picks this up)

- Postgres+pgvector runs via **colima** (no Docker Desktop installed) + `docker-compose.yml` at repo root.
  Before starting work, check it's up: `colima status` / `docker compose ps`. If not running:
  `colima start && docker compose up -d`.
- `.env` has `DATABASE_URL=postgresql://ito:change_me_before_use@localhost:5432/ito_posts` — already loadable
  via `config.settings.load_settings()` (`settings.database_url`).
- 250 posts are already ingested (`python -m processors.run_db_ingest` if the container was reset).
- Existing DB access layer: storage/vector_store.py — `get_connection()`, `create_schema()`,
  `insert_posts()`. This plan adds a fourth function, `find_similar()`.
- Existing embedding code: processors/embedder.py — `embed_batch()` embeds *documents*
  (`task_type="RETRIEVAL_DOCUMENT"`) in bulk. This plan adds a small sibling, `embed_query()`, for embedding
  a single *query* at request time (see Decision #1 below for why the task_type differs).

---

## Scope boundaries

**Included:**
- FastAPI app with one retrieval endpoint + a health check, run locally via `uvicorn`.
- The cosine-distance SQL query against the existing `posts` table.
- Pydantic request/response models (auto-generates the OpenAPI page FastAPI serves at `/docs`).
- Unit tests with the DB and Gemini calls mocked (repo convention — no real network/DB calls in tests).
- A manual local verification pass against the real running Postgres container + real Gemini API.

**Excluded (deliberately, do not build these now):**
- Nginx reverse proxy + actual EC2 deployment — blocked on the same EC2/EBS details as T1.4/T1.5's Phase 2
  (see T1.4_DATABASE_PLAN.md). Document the Nginx config as a reference, don't wire it up or test it, since
  there's no server to run it on yet.
- Authentication / rate limiting — internal test API for now.
- Writing new posts back to the DB via the API — this endpoint is **read-only**.
- Any "score this post" logic beyond returning the nearest historical posts + their engagement numbers.
  Erdal's T2.2 spec only asks for retrieval ("fetch the 10 closest... records"), not a computed score —
  that's future work, not part of this task.

---

## Steps

### 1. Add dependencies to requirements.txt
`fastapi>=0.110.0`, `uvicorn[standard]>=0.29.0`, `httpx>=0.27.0` (httpx is what FastAPI's `TestClient` needs
under the hood for tests — not a runtime dependency of the app itself, but required to test it).

### 2. Add `find_similar()` to storage/vector_store.py
New function, same small/heavily-commented style as the existing three:
```python
def find_similar(conn, query_vector: np.ndarray, limit: int = 10) -> list[dict]:
    """Return the `limit` posts whose embedding is closest (cosine distance)
    to query_vector, ordered nearest-first. Uses the halfvec(3072) HNSW
    index defined in storage/schema.sql — the query MUST cast both sides to
    halfvec(3072) to actually hit that index (see T1.4_DATABASE_PLAN.md).
    Returns list of dicts with post_id, content, engagement fields, and the
    computed cosine_distance for each match.
    """
```
Query shape:
```sql
SELECT post_id, content, likes, comments, shares, total_engagement,
       engagement_percentile, engagement_zscore,
       embedding::halfvec(3072) <=> %s::halfvec(3072) AS cosine_distance
FROM posts
ORDER BY embedding::halfvec(3072) <=> %s::halfvec(3072)
LIMIT %s
```
Use `cur.execute(..., (query_vector, query_vector, limit))` and `cur.fetchall()` with
`row_factory=psycopg.rows.dict_row` (or zip column names manually) so callers get plain dicts.

### 3. Add `embed_query()` to processors/embedder.py
Small sibling of `embed_batch()` for a single query string at request time — **see Decision #1** for why
this needs its own function rather than reusing `embed_batch()`.
```python
def embed_query(text: str, settings: Settings) -> np.ndarray:
    """Embed a single query string for similarity search against stored
    posts. Uses task_type="RETRIEVAL_QUERY" (not RETRIEVAL_DOCUMENT, which
    embed_batch() uses for stored posts) - Gemini's asymmetric retrieval
    mode expects queries and documents embedded with matching-but-different
    task types for best retrieval accuracy. Reuses the same retry logic
    (_embed_with_retry) as embed_batch().
    """
```
Refactor opportunity (keep small): `_embed_with_retry` already takes a `batch: list[str]`, so
`embed_query` can just call it with a single-element list and a `task_type="RETRIEVAL_QUERY"` config, then
return `vectors[0]`. Don't duplicate the retry loop.

### 4. Create the `api/` package
New top-level package (sibling to `dashboard/`, `processors/`, `storage/` — its own concern, same pattern
this repo already uses for separating responsibilities):

- `api/__init__.py` — empty.
- `api/schemas.py` — Pydantic models (this *is* T2.3, the "API Contract Definition"):
  ```python
  class SimilarPostsRequest(BaseModel):
      content: str = Field(..., min_length=1, description="Draft post text to find similar posts for")
      limit: int = Field(default=10, ge=1, le=50)

  class SimilarPost(BaseModel):
      post_id: str
      content: str
      likes: int
      comments: int
      shares: int
      total_engagement: int
      engagement_percentile: float
      engagement_zscore: float
      cosine_distance: float

  class SimilarPostsResponse(BaseModel):
      query_content: str
      results: list[SimilarPost]
  ```
- `api/main.py` — FastAPI app + two routes:
  - `GET /health` → `{"status": "ok"}` (simple readiness check, no DB/Gemini call).
  - `POST /api/v1/similar-posts` → body: `SimilarPostsRequest`, response: `SimilarPostsResponse`.
    Handler: `embed_query(request.content, settings)` → `find_similar(conn, vector, request.limit)` →
    wrap rows into `SimilarPost` objects.
  - Load `Settings` once at module scope via `load_settings()` (same pattern every other entry point in
    this repo uses), open a fresh `get_connection()` per request (simplest correct option — a connection
    pool is a legitimate future optimization but is over-engineering for this phase's scope).
  - FastAPI auto-serves interactive docs at `/docs` and the raw spec at `/openapi.json` — this alone
    satisfies T2.3's literal success criterion, no extra work needed.

### 5. Tests
- `tests/test_vector_store.py` — add `find_similar()` tests (mock cursor/`fetchall`, assert the SQL string
  contains `halfvec(3072)` and `<=>` and `LIMIT`, assert returned dicts match mocked rows). Same mocking
  style as the existing `insert_posts`/`create_schema` tests in that file.
- `tests/test_embedder.py` — add `embed_query()` tests (mock `genai.Client`, assert `task_type` passed to
  the config is `"RETRIEVAL_QUERY"`, assert it returns a 1-D array not 2-D). Mirror the existing
  `embed_batch` mocking pattern.
- `tests/test_api.py` (new) — use FastAPI's `TestClient` against `api.main.app`, with `embed_query` and
  `find_similar` both patched (no real DB/Gemini calls in unit tests, per repo convention — see how
  `tests/test_embedder.py` and `tests/test_vector_store.py` already do this). Cover:
  - `GET /health` → 200.
  - `POST /api/v1/similar-posts` with valid body → 200, response shape matches `SimilarPostsResponse`.
  - Empty `content` → 422 (Pydantic validation, free from `Field(min_length=1)`).
  - `limit` out of range (e.g. 0 or 100) → 422 (free from `Field(ge=1, le=50)`).

### 6. Manual local verification (real DB + real Gemini API)
1. Confirm the container's running: `docker compose ps`.
2. `uvicorn api.main:app --reload --port 8000` (from repo root, venv activated).
3. Open `http://localhost:8000/docs` — confirm the interactive OpenAPI page renders and shows both routes.
4. `curl -X POST http://localhost:8000/api/v1/similar-posts -H "Content-Type: application/json" -d '{"content": "Excited to announce our new backend engineering hire!", "limit": 5}'`
   — confirm 5 results come back, sorted by ascending `cosine_distance`, with real `engagement_percentile`
   values from the 250 ingested posts.
5. Timing: measure **just the SQL query** (already proven at 1.9ms in T1.4_DATABASE_PLAN.md) separately from
   the **whole HTTP round trip** (which includes one live Gemini API call, typically ~100-300ms over the
   network — see Decision #2, this is NOT something to optimize away, it's an external API call).

---

## Decisions

1. **`RETRIEVAL_QUERY` vs `RETRIEVAL_DOCUMENT` task_type:** stored posts were embedded with
   `task_type="RETRIEVAL_DOCUMENT"` (see T1.3_EMBEDDING_PLAN.md). Gemini's embedding model is asymmetric —
   it expects the *query* side of a search to be embedded with `task_type="RETRIEVAL_QUERY"` for best
   accuracy. Getting this right matters more than any other single decision in this phase; using the wrong
   task_type won't error, it'll just silently produce worse matches.
2. **Where the 150ms budget applies:** Erdal's T2.2 success criterion says the endpoint should "yield
   matching historical records... in under 150ms." Read literally, that's about the **SQL retrieval step**
   (already proven at 1.9ms), not the full request including an external Gemini API call to embed the
   incoming text (that's a separate, uncontrollable network cost). Don't chase "under 150ms total including
   the Gemini call" as a goal — it's not what was asked for and isn't fully within this codebase's control.
3. **One connection per request, no pooling:** simplest correct thing for this phase's scale (250 rows,
   local/dev use). A connection pool (e.g. `psycopg_pool`) is a reasonable future optimization once this
   moves to EC2 with real traffic, but adding it now would be scope creep.
4. **Nginx config:** write it as a reference file/comment only (e.g. a `deploy/nginx.conf.example`), don't
   wire it up or test it — there's no EC2 instance to run it on yet, mirroring the T1.4 Phase 2 blocker.

---

## Relevant files

- `requirements.txt` — add `fastapi`, `uvicorn[standard]`, `httpx`
- `processors/embedder.py` — add `embed_query()`, reusing `_embed_with_retry`
- `storage/vector_store.py` — add `find_similar()`
- `api/__init__.py`, `api/main.py`, `api/schemas.py` — new package
- `tests/test_embedder.py`, `tests/test_vector_store.py` — extend with new function tests
- `tests/test_api.py` — new, FastAPI `TestClient` tests

## Verification checklist

1. `python -m pytest tests/ -q` — all tests pass (existing 70 + new ones), nothing hits a real DB/API.
2. Manual steps 1-5 above against the real local Postgres container + real Gemini API.
3. Confirm `/docs` is reachable and shows a complete, accurate OpenAPI contract (T2.3's literal success
   criterion).
4. Confirm the SQL query alone stays well under 150ms (it will — already proven at 1.9ms).

## What this phase does NOT do

- Does not deploy to EC2 or configure Nginx (Phase 2 deployment, same blocker as T1.4/T1.5).
- Does not add authentication, rate limiting, or a connection pool.
- Does not compute a "score" for the submitted post — only returns its nearest neighbours and their real
  engagement numbers, exactly as Erdal's T2.2 spec asks for. Scoring/prediction is a later phase.
