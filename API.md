# ITO API — Frontend Contract

Human-readable guide for the product frontend. Live machine-readable schema: [http://localhost:8000/docs](http://localhost:8000/docs) (`/openapi.json`).

Base URL (local Compose): `http://localhost:8000`

---

## Run the API

```bash
docker compose up -d
curl -s localhost:8000/health
# → {"status":"ok"}
```

Or locally: `uvicorn api.main:app --reload --port 8000`

---

## Versioning

All product routes use the `/api/v1` prefix. Breaking changes require a new major path (`/api/v2/...`). Additive fields are allowed within v1.

---

## CORS

Browser frontends need CORS. Allowed origins come from `CORS_ALLOWED_ORIGINS` (comma-separated).

Default: `http://localhost:3000,http://localhost:5173`

---

## Auth (current)

**None.** `user_id` / `subscriber_id` are trusted client fields for local/dev. Do not expose this API publicly without auth, rate limits, and tenant checks.

---

## Errors

| Status | Meaning |
|--------|---------|
| `422` | Validation / domain rejection (`detail` string or Pydantic error list) |
| `404` | Resource missing |
| `500` | Unexpected server / agent failure |
| `503` | Dependency missing (e.g. `DATABASE_URL`) |

FastAPI error body: `{"detail": "..."}` or `{"detail": [ {...}, ... ]}` for request validation.

---

## Recommended UI flows

### Draft studio

1. **Compare only** → `POST /api/v1/similar-posts`
2. **Score + diagnose + variants** → `POST /api/v1/evaluate`
3. Optional lenses → `POST /api/v1/critique`
4. Optional rewrites → `POST /api/v1/optimise` (pass objection / baseline from evaluate or critique)

### Personalization (LinkedIn account box)

1. `POST /api/v1/subscriber-evidence/briefs` — submit public profile URL + niche + consent
2. Show proposed plan → `POST .../approve`
3. Poll `GET .../status`, `.../jobs`, `.../receipts`
4. Optional `POST .../refresh-now` (may spend Apify budget)
5. Pause / resume as needed

Scrapes do **not** run inside approve; the worker (or refresh-now) collects under caps.

### Corpus → vector DB

1. `POST /api/v1/corpus/ingest` → `202` + job id
2. Poll `GET /api/v1/corpus/jobs/{job_id}`
3. `GET /api/v1/corpus/stats` for post count / benchmarks

### Feedback loop

1. `POST /api/v1/feedback/run` — drain pending feedback jobs
2. `GET /api/v1/feedback/coverage` — labeled coverage
3. `GET /api/v1/feedback/review` — pending hybrid lessons

Evaluate already injects feedback lessons when injection flags are on.

### Dashboard stats

`GET /api/v1/stats` (or `/stats/corpus`, `/stats/feedback`, `/stats/budget`)

---

## Endpoints

### Ops

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness |
| `GET` | `/metrics` | Prometheus (ops; not product UI) |

### Compare / evaluate

#### `POST /api/v1/similar-posts`

Nearest historical posts (cosine similarity over pgvector).

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `content` | string | required |
| `limit` | int | 1–50, default 10 |
| `user_id` | string? | scope to subscriber corpus with global fallback |

**Example**

```bash
curl -s localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content":"Tips for hiring engineers in 2026","limit":5}'
```

#### `POST /api/v1/evaluate`

Full multi-agent cycle: neighbors → predictor → diagnostics → variants (+ optional voice / SEO / trends / visual).

**Key body fields:** `content`, `neighbor_limit` (10–100), `variant_strategy` (`dimension`\|`narrative`\|`tiered`), `user_id`, `use_voice_profile`, `seo_mode`, `use_google_trends`, `use_visual_diagnostics`, `image_url`.

#### `POST /api/v1/critique`

Independent C-suite / practitioner / peer critic. Body: `{ "content": "..." }`.

#### `POST /api/v1/optimise`

Independent Stage-5 rewrites (maximizer / counter / brand_purist).

**Body:** `content`, optional `primary_objection`, `baseline_percentile`, `baseline_total_engagement`, `user_id`, `use_voice_profile`.

---

### Personalization (subscriber evidence)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/subscriber-evidence/briefs` | Create/revise brief + propose plan (**201**) |
| `GET` | `/api/v1/subscriber-evidence/briefs/{subscriber_id}` | Read brief + plan |
| `POST` | `.../approve` | Approve plan (enables worker; no inline scrape) |
| `POST` | `.../pause` / `.../resume` | Collection controls |
| `GET` | `.../receipts` | Recent collection receipts |
| `GET` | `.../jobs` | Recent collection jobs |
| `GET` | `.../status` | Coverage + budget (“personalization strength”) |
| `POST` | `.../refresh-now` | Run one collection cycle now (may spend) |

**Brief create body**

| Field | Required | Notes |
|-------|----------|-------|
| `subscriber_id` | yes | Account id |
| `public_profile_url` | yes | Public HTTPS LinkedIn member URL |
| `profile_authorized` | yes | Must be `true` |
| `role_description` | yes | What they do |
| `primary_niche` | yes | e.g. `sports` |
| `sub_niche` | no | e.g. `football coaching` |
| `target_audience` | yes | |
| `objectives` | no | ≤10 strings |
| `locale` | no | |
| `seed_accounts` | no | ≤20 profile URLs/handles |

**Status response (summary):** `brief_status`, `plan_status`, `coverage.accepted_count`, `budget.lifetime_baseline_spent_usd`, caps.

---

### Corpus

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/corpus/ingest` | Queue embed+ingest or ingest-only (**202**) |
| `GET` | `/api/v1/corpus/jobs/{job_id}` | Job status / result |
| `GET` | `/api/v1/corpus/stats` | `post_count` + corpus benchmarks |

**Ingest body**

| Field | Notes |
|-------|-------|
| `mode` | `embed_and_ingest` (default) or `ingest_only` |
| `processed_file` | Optional path to analysed JSONL |
| `embeddings_file` | Optional `.npy` for `ingest_only` |
| `limit` | Optional cap for cheap embed test runs |

Poll until `status` is `completed` or `failed`. On success, `result.upserted` is the row count.

---

### Feedback

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/feedback/run` | Process pending feedback jobs |
| `GET` | `/api/v1/feedback/coverage` | Validated / with / missing feedback counts |
| `GET` | `/api/v1/feedback/review?limit=30` | Pending hybrid lessons |

**Run body (optional):** `{ "limit": 20 }`

---

### Stats

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/stats` | Corpus + feedback + budget rollup |
| `GET` | `/api/v1/stats/corpus` | Same as `/corpus/stats` |
| `GET` | `/api/v1/stats/feedback` | Coverage + learning flags |
| `GET` | `/api/v1/stats/budget` | Agentic Apify/Gemini spend vs caps |

---

### Company Search & Bulk Corpus Ingestion

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/companies/resolve-urls` | Resolve bulk company names to canonical LinkedIn URLs |
| `POST` | `/api/v1/corpus/company-collect` | Scrape 10 most recent posts from company pages and ingest into vector corpus |

**Resolve body:**
```json
{
  "companies": ["Stripe", "OpenAI", "https://www.linkedin.com/company/microsoft"]
}
```

**Company Collect body:**
```json
{
  "companies": ["Stripe", "OpenAI"],
  "max_posts_per_company": 10,
  "with_gemini": true,
  "run_async": false
}
```

---

## Frontend screen → endpoint map

| UI screen | Endpoints |
|-----------|-----------|
| Neighbor explorer | `POST /similar-posts` |
| Draft scorecard | `POST /evaluate` |
| Audience lenses | `POST /critique` |
| Rewrite picker | `POST /optimise` |
| Evidence onboarding | `POST/GET briefs` + `approve` |
| Evidence controls | `pause` / `resume` / `refresh-now` |
| Personalization meter | `GET .../status` |
| Transparency | `receipts`, `jobs` |
| Corpus admin | `corpus/ingest` + `corpus/jobs/{id}` |
| Feedback ops | `feedback/run`, `coverage`, `review` |
| Dashboard numbers | `GET /stats` |

---

## Out of scope (for now)

- Auth / API keys / rate limits
- Delete/export personal evidence
- SSE streaming evaluate steps
- Seed approve/reject as separate product APIs
- Ops Streamlit surfaces (agentic tick flags, Apify proofs) — keep internal
