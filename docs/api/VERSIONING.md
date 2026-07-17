# API versioning and backward compatibility

This document defines how the IntoTheOpen backend evolves its HTTP API for
frontend (Lovable) integration. The machine-readable contract is the OpenAPI
spec at `/openapi.json` (snapshot: `openapi.json` in the repo root).

## Strategy

| Topic | Policy |
| ----- | ------ |
| **Versioning mechanism** | Path-based — stable routes live under `/api/v1/` |
| **Current stable version** | `v1` |
| **Health probe** | `GET /health` returns `api_version: "v1"` (path version, not OpenAPI `info.version`) |
| **OpenAPI `info.version`** | Semantic API release label (currently `1.0.0`); bump on contract publication changes |

We do **not** use header-based versioning for the MVP. Clients should target
`/api/v1/...` explicitly.

## Breaking vs non-breaking changes

### Non-breaking (allowed within `v1`)

- Adding **optional** request fields
- Adding **optional** response fields
- Adding new endpoints under `/api/v1/`
- Widening validation (e.g. longer `content` allowed) when clients are unaffected
- Adding new keys to `diagnostics` (values remain `DiagnosticResult` shaped)

### Breaking (requires `/api/v2/` or explicit client migration)

- Removing or renaming request/response fields
- Changing field types or requiredness
- Changing HTTP method or URL for an existing operation
- Changing the meaning of an existing field (semantic break)

Breaking changes ship on a **new path prefix** (`/api/v2/...`). `v1` remains
available until the deprecation window ends.

## Deprecation policy

1. Announce deprecation in the GitHub issue/PR and in `docs/api/API_CONTRACT.md`.
2. Keep the old path operational for at least **6 months** after announcement.
3. Optionally return a `Sunset` HTTP header with the planned removal date.
4. Remove `v1` only after the frontend confirms migration (tracked in issue #27
   go-live checklist).

## Error contract

OpenAPI documents two error shapes:

| HTTP | Model | Purpose |
| ---- | ----- | ------- |
| 422 | `ValidationErrorResponse` | Pydantic request validation |
| 502/503 | `ApiErrorResponse` | Provider or dependency outage |
| 500 | `ApiErrorResponse` | Unexpected server failure |

Runtime mapping of all failures to `ApiErrorResponse` is implemented in
`api/errors.py` (issue **#7**). Validation failures remain HTTP 422 with
`ValidationErrorResponse`.

## Client generation

Generate TypeScript types from the committed snapshot:

```bash
npx openapi-typescript openapi.json -o src/api/schema.d.ts
```

Or from a running server:

```bash
curl -s localhost:8000/openapi.json -o openapi.json
npx openapi-typescript openapi.json -o src/api/schema.d.ts
```

CI contract-break detection and automated client publishing are tracked in issue **#24**.

## Related issues

| Issue | Scope |
| ----- | ----- |
| #6 | Contract + versioning policy (this document) |
| #7 | Error envelope runtime implementation |
| #24 | CI OpenAPI diff + generated client checks |
| #23 | CORS trusted-origin policy |
| #3 / #9 | Auth headers (will appear in OpenAPI when merged) |
