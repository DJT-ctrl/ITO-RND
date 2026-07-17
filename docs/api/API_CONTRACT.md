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
| `POST` | `/api/v1/similar-posts` | `SimilarPostsRequest` | `SimilarPostsResponse` | Corpus similarity search |
| `POST` | `/api/v1/evaluate` | `EvaluateRequest` | `EvaluateResponse` | Full agent evaluation cycle |

`GET /metrics` (Prometheus) is intentionally **excluded** from the public
frontend contract.

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
| `variant_strategy` | `"dimension"` \| `"narrative"` \| `"tiered"` | `"dimension"` | Variant engine axis |
| `reembed_variant_neighbors` | boolean | `false` | Per-variant neighbor re-fetch |
| `user_id` | string | null | Personalization + scoped retrieval |
| `use_voice_profile` | boolean | `true` | No effect without `user_id` |
| `seo_mode` | `"corpus"` \| `"gemini_only"` | server default | SEO diagnostic mode |
| `use_google_trends` | boolean | server default | Tier-2 timeliness signals |

**Response 200** — `EvaluateResponse`

| Field | Type | Notes |
| ----- | ---- | ----- |
| `draft_content` | string | Echo of input |
| `similar_posts` | `SimilarPost[]` | Retrieval neighbors |
| `voice_profile` | `VoiceProfile` \| null | Present when `user_id` has enough posts |
| `predictor_result` | `PredictorResult` \| null | Engagement prediction |
| `diagnostics` | `Record<string, DiagnosticResult>` | Keys typically `seo`, `clarity`, `tone` |
| `variants` | `VariantResult[]` | Up to 3 ranked rewrites |
| `errors` | string[] | Non-fatal agent failures |
| `run_metadata` | `RunMetadata` \| null | Telemetry summary |
| `query_embedding` | number[] \| null | Query vector (JSON list) |
| `embedding_model_version` | string \| null | Embed model id |

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

curl -s localhost:8000/api/v1/similar-posts \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here", "limit": 5}'

curl -s localhost:8000/api/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"content": "Your draft post text here", "variant_strategy": "dimension"}'
```

---

## Model source files

| Model | Python module |
| ----- | ------------- |
| Request/response + errors | `api/schemas.py` |
| `PredictorResult` | `api/schemas.py` |
| `DiagnosticResult` | `api/schemas.py` |
| `RunMetadata` | `telemetry/schemas.py` |
