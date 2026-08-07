# API contract (v1)

Stable HTTP contract for frontend integration. Authoritative schema:
[`openapi.json`](../../openapi.json) (generated from FastAPI models).

**Versioning policy:** [`VERSIONING.md`](VERSIONING.md)

## Base URL

| Environment | Base URL |
| ----------- | -------- |
| Local (docker compose) | `http://localhost:8000` |
| Production | TBD — set via deployment runbook (#20) |

Interactive docs: `GET /docs` · Machine spec: `GET /openapi.json`

---

## Endpoints

| Method | Path | Request model | Response model | Notes |
| ------ | ---- | ------------- | -------------- | ----- |
| `GET` | `/health` | — | `HealthResponse` | Liveness; no auth |
| `GET` | `/api/v1/agents` | — | `AgentCatalogResponse` | Agent registry for UI discovery |
| `POST` | `/api/v1/similar-posts` | `SimilarPostsRequest` | `SimilarPostsResponse` | Corpus similarity search |
| `POST` | `/api/v1/evaluate` | `EvaluateRequest` | `EvaluateResponse` | Full agent evaluation cycle |
| `POST` | `/api/v1/critique` | `CritiqueRequest` | `AudienceCriticOutput` | Standalone audience critic (not part of evaluate loop) |
| `POST` | `/api/v1/optimise` | `OptimiseRequest` | `SynthesisResult` | Standalone Stage 5 synthesis (does not replace evaluate variants) |

`GET /metrics` (Prometheus) is intentionally **excluded** from the public
frontend contract.

Product frontend scope and endpoint→screen mapping: [`Phase_12.md`](../../Phase_12.md).

---

## `GET /health`

**Response 200**

```json
{
  "status": "ok",
  "api_version": "v1"
}
```

---

## `GET /api/v1/agents`

List active backend agents for frontend discovery (predictor, diagnostics, variant engine).

**Response 200** — `AgentCatalogResponse` with `agents[]` of `AgentDescriptor`:

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | string | Stable machine id (e.g. `predictor`, `seo`) |
| `name` | string | UI label |
| `kind` | `"predictor"` \| `"diagnostic"` \| `"variant"` \| `"system"` | Grouping / iconography |
| `stage` | `"setup"` \| `"evaluation"` \| `"optimization"` \| `"reporting"` \| `"monitoring"` | Workflow stage |
| `description` | string | Short purpose |

---

## `POST /api/v1/similar-posts`

Find nearest historical posts for a draft.

**Request**

| Field | Type | Required | Default | Notes |
| ----- | ---- | -------- | ------- | ----- |
| `content` | string | yes | — | min length 1 |
| `limit` | integer | no | 10 | 1–50 |
| `user_id` | string | no | null | Scope retrieval to subscriber corpus |

**Response 200** — `SimilarPostsResponse` with `query_content` echo and `results[]`
of `SimilarPost` objects (engagement stats + optional enrichment fields).

**Errors**

| Status | Body | When |
| ------ | ---- | ---- |
| 422 | `ValidationErrorResponse` | Empty `content`, `limit` out of range |
| 500 | `ApiErrorResponse` (documented) | Embed/DB failure (plain `detail` until #7) |

---

## `POST /api/v1/evaluate`

Run predictor, diagnostic workers, and variant engine on a draft.

**Request highlights**

| Field | Type | Default | Notes |
| ----- | ---- | ------- | ----- |
| `content` | string | — | Draft to evaluate |
| `neighbor_limit` | integer | `10` | 10–100 neighbors for grounding / comparison |
| `variant_strategy` | `"dimension"` \| `"narrative"` \| `"tiered"` | `"dimension"` | Variant engine axis |
| `reembed_variant_neighbors` | boolean | `false` | Re-embed each variant; adds up to 3 embeddings plus 6 scoped/global retrieval queries |
| `user_id` | string | null | Personalization + scoped retrieval |
| `use_voice_profile` | boolean | `true` | No effect without `user_id` |
| `seo_mode` | `"corpus"` \| `"gemini_only"` | server default | SEO diagnostic mode |
| `use_google_trends` | boolean | server default | Tier-2 timeliness signals |
| `use_visual_diagnostics` | boolean | server default | Opt-in when `image_url` set |
| `image_url` | string | null | Ignored unless visual diagnostics enabled |

**Response 200** — `EvaluateResponse`

| Field | Type | Notes |
| ----- | ---- | ----- |
| `draft_content` | string | Echo of input |
| `similar_posts` | `SimilarPost[]` | Retrieval neighbors |
| `voice_profile` | `VoiceProfile` \| null | Present when `user_id` has enough posts |
| `predictor_result` | `PredictorResult` \| null | Engagement prediction |
| `diagnostics` | `Record<string, DiagnosticResult>` | Keys typically `seo`, `clarity`, `tone` |
| `variants` | `VariantResult[]` | Up to 3 ranked rewrites |
| `cross_references` | `CrossReferenceResult` \| null | Curated stronger close matches and bounded adaptation feedback |
| `errors` | string[] | Non-fatal agent failures |
| `run_metadata` | `RunMetadata` \| null | Telemetry summary |
| `query_embedding` | number[] \| null | Query vector (JSON list; omit from UI) |
| `embedding_model_version` | string \| null | Embed model id |
| `visual_diagnostics_requested` | boolean | Whether visual diagnostics were requested |

### `DiagnosticResult` (per check)

| Field | Type |
| ----- | ---- |
| `score` | number (0–10) |
| `flaws` | string[] |
| `advantages` | string[] |
| `improvements` | string[] |

### `VariantResult`

| Field | Type |
| ----- | ---- |
| `variant_text` | string |
| `rationale` | string |
| `strategy_label` | string |
| `predicted_engagement_percentile` | number (0–100) |
| `predicted_total_engagement` | integer |

### `CrossReferenceResult`

`cross_references` is additive and may be `null` when the feature is disabled.
When present, it is derived from a **separate global candidate search**, not
from the user-scoped prediction neighbors. Selection is deterministic: a post
must be sufficiently semantically close, non-anomalous, and materially above
the draft's neighbor baseline. Audience-adjusted percentile is preferred when
available.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `status` | `"ready"` \| `"insufficient_evidence"` \| `"analysis_unavailable"` | Never infer generic comparison advice when evidence is unavailable |
| `baseline_percentile` | number \| null | Neighbor-based performance baseline used for uplift |
| `references` | `CrossReferencePost[]` | At most three deterministic selections, each with the source `SimilarPost`, normalized uplift, selection facts, and optional analyst adaptation |
| `overall_feedback` | string[] | Bounded explanatory feedback for the selected references only |
| `caveats` | string[] | Observational-performance limitations and availability notes |

Frontend behavior: render a compact Evidence tab or section for `ready` and
`analysis_unavailable` references. For `insufficient_evidence`, explain that
no sufficiently close higher-performing reference was found; do not substitute
generic copy advice. Treat source posts as inspiration only, never copy their
wording or claim the displayed pattern caused engagement.

---

## `POST /api/v1/critique`

Independent synthetic-audience critic. **Not** part of the evaluate loop — does not affect predictor, diagnostics, or variants.

**Request**

| Field | Type | Required | Notes |
| ----- | ---- | -------- | ----- |
| `content` | string | yes | min length 1 |

**Response 200** — `AudienceCriticOutput` (see OpenAPI / `agents.audience_critic`).

---

## `POST /api/v1/optimise`

Independent Stage 5 synthesis. Does **not** replace evaluate-loop variants. Soft-fails scoring into `result.errors`.

**Request highlights**

| Field | Type | Default | Notes |
| ----- | ---- | ------- | ----- |
| `content` | string | — | Draft to optimise |
| `primary_objection` | string | null | Optional C-suite objection (e.g. from `/critique`) |
| `baseline_percentile` | number | null | 0–100; original-draft predicted percentile |
| `baseline_total_engagement` | integer | null | Original-draft predicted engagement |
| `user_id` | string | null | Neighbor scoping / voice profile |
| `use_voice_profile` | boolean | `true` | No effect without `user_id` |

**Response 200** — `SynthesisResult` (see OpenAPI / `agents.synthesis`).

---

## Error handling for frontend

### Validation (422) — active today

FastAPI returns `ValidationErrorResponse`:

```json
{
  "detail": [
    {
      "loc": ["body", "content"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```

**UI guidance:** map `loc` + `msg` to form field errors.

### Server errors (500) — documented; runtime in #7

Target envelope (`ApiErrorResponse`):

```json
{
  "code": "EMBED_FAILED",
  "message": "Failed to embed query text.",
  "retryable": true,
  "details": { "provider": "google" }
}
```

Until #7 merges, some 500 responses may still be `{"detail": "..."}`. Frontend
should handle both temporarily.

---

## curl examples

```bash
curl -s localhost:8000/health | jq .

curl -s localhost:8000/api/v1/agents | jq .

curl -s localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here", "limit": 5}'

curl -s localhost:8000/api/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here", "variant_strategy": "dimension"}'

curl -s localhost:8000/api/v1/critique \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here"}'

curl -s localhost:8000/api/v1/optimise \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here"}'
```

---

## Model source files

| Model | Python module |
| ----- | ------------- |
| Request/response + errors | `api/schemas.py` |
| `AgentDescriptor` / `AgentCatalogResponse` | `api/schemas.py` |
| `CritiqueRequest` / `OptimiseRequest` | `api/schemas.py` |
| `PredictorResult` | `api/schemas.py` |
| `DiagnosticResult` | `api/schemas.py` |
| `AudienceCriticOutput` | `agents/audience_critic.py` |
| `SynthesisResult` | `agents/synthesis.py` |
| `RunMetadata` | `telemetry/schemas.py` |
