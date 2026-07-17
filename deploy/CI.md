# CI pipeline — quality gates (issues #5 + #10)

GitHub Actions workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

## Jobs

| Job | What it does | Typical runtime |
| --- | ------------ | --------------- |
| **lint** | `ruff check` on core Python packages | ~1 min |
| **test** | `pytest -q` on Python **3.11** and **3.12** (unit only; integration excluded) | ~3–8 min per matrix leg |
| **integration** | `docker compose` (db + migrate + api + prometheus) → seed → critical API journeys | ~10–15 min |

**Total PR pipeline:** ~12–25 minutes (lint + test matrix run in parallel; integration waits for both).

Issue #5 built the CI checkpoint (lint + unit matrix). Issue #10 replaced the light
smoke curl checks with a full docker-compose integration suite.

## Install commands (match CI locally)

```bash
# Lint
pip install ruff
ruff check api agents config tests storage processors validation_pipeline feedback telemetry scrapers

# Unit tests (same env vars CI uses; exclude docker-compose integration)
export GEMINI_API_KEY=ci-fake-gemini-key GOOGLE_API_KEY=ci-fake-gemini-key API_AUTH_ENABLED=false
pytest -q -m "not integration"

# Integration suite (requires Docker)
./scripts/ci-integration.sh
```

When issue #4 lockfile is on `main`, Python **3.12** installs from pinned `requirements.txt`;
Python **3.11** installs from `requirements.in` (source constraints).

## Integration suite (issue #10)

Stack: `docker compose -f docker-compose.yml -f docker-compose.ci.yml` brings up
`db`, `migrate`, `api`, and `prometheus` only (Grafana / cAdvisor / node-exporter
are profile-gated out of CI).

| Test file | What it proves | If it fails, blame… |
| --------- | -------------- | ------------------- |
| `tests/integration/test_infra.py` | migrate + `/health` + schema | Docker / Postgres / schema |
| `tests/integration/test_seed.py` | seeded posts + embeddings | Seed script / ingest |
| `tests/integration/test_api_similar_posts.py` | `POST /similar-posts` ranking | API ↔ DB ↔ pgvector |
| `tests/integration/test_api_evaluate.py` | `POST /evaluate` stub path | API ↔ DB (evaluate wiring) |
| `tests/integration/test_telemetry.py` | `/metrics` + Prometheus `up{job="ito-api"}` | Telemetry wiring |

**Stack ports (defaults):** API `18000`, Postgres `15432`, Prometheus `19090`
(isolated from a normal local stack on 8000/5432/9090). Override via
`API_HOST_PORT` / `DB_HOST_PORT` / `PROMETHEUS_HOST_PORT`.

**CI stubs (off by default):** `CI_INTEGRATION_STUBS=true` makes `embed_query`
deterministic; `CI_EVALUATE_STUB=true` returns a canned evaluate response after a
real DB neighbor fetch. No live Gemini calls in CI.

**Artifacts (GitHub Actions):** on every integration job, upload
`integration-results.xml` (JUnit) and, on failure, `compose-logs.txt`.

## Merge gate

Enable in GitHub → **Settings → Branches → Branch protection rules** for `main`:

- [x] Require status checks to pass before merging
- Required checks: `Lint (ruff)`, `Test (Python 3.11)`, `Test (Python 3.12)`, `Docker Compose integration`

Until branch protection is enabled, CI still runs and shows red/green on PRs but cannot block merges by itself.

## Flaky-test policy

1. **CI retries once** — the unit test job uses `nick-fields/retry` with `max_attempts: 2`.
2. **If a test fails twice**, treat it as a real failure — fix or quarantine the test in a follow-up PR; do not raise retry count without team agreement.
3. **No retry on lint or integration** — those should be deterministic (infra + seeded data).
4. **Suspected flakes** — note in the PR description and link the failing run; if the same test flakes twice in a week, open an issue to fix root cause.

## Status badge

Add to README (already wired when workflow is on `main`):

```markdown
[![CI](https://github.com/intotheopen/intotheopen-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/intotheopen/intotheopen-backend/actions/workflows/ci.yml)
```
