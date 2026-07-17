# API error codes (v1)

Stable machine-readable `code` values returned in `ApiErrorResponse` for
non-validation failures. Validation failures use HTTP 422 + `ValidationErrorResponse`.

| Code | HTTP | Retryable | Typical cause |
| ---- | ---- | --------- | ------------- |
| `BAD_REQUEST` | 400 | no | Invalid client input surfaced as `ValueError` |
| `UNAUTHORIZED` | 401 | no | Missing/invalid credentials (future #3) |
| `FORBIDDEN` | 403 | no | Authenticated but not allowed (future #3/#9) |
| `NOT_FOUND` | 404 | no | Unknown resource |
| `RATE_LIMITED` | 429 | yes | Rate limit exceeded (future #3) |
| `CONFIG_MISSING` | 503 | no | Required env config (e.g. `GEMINI_API_KEY`) |
| `EMBED_FAILED` | 500 | yes | Embedding step failed |
| `PROVIDER_ERROR` | 502/503 | varies | Gemini / external AI provider failure |
| `DATABASE_UNAVAILABLE` | 503 | yes | Postgres connection/query failure |
| `AGENT_UNAVAILABLE` | 503 | no | Evaluation agents cannot be initialized |
| `SERVICE_UNAVAILABLE` | 503 | yes | Generic upstream outage |
| `INTERNAL_ERROR` | 500 | yes | Unexpected server failure |

## Frontend handler sketch

```typescript
async function handleApiError(response: Response) {
  if (response.status === 422) {
    const body = await response.json();
    return { kind: "validation", fields: body.detail };
  }
  const body = await response.json();
  if (body.code && body.message !== undefined) {
    return { kind: "api", ...body };
  }
  // Legacy fallback (should not occur after #7)
  return { kind: "legacy", message: body.detail ?? "Unknown error" };
}
```

Implementation: `api/errors.py` · OpenAPI examples: `api/openapi_examples.py`
