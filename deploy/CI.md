# CI pipeline — quality gates (issue #5)

GitHub Actions workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

## Jobs

| Job | What it does | Typical runtime |
| --- | ------------ | --------------- |
| **lint** | `ruff check` on core Python packages | ~1 min |
| **test** | `pytest -q` on Python **3.11** and **3.12** | ~3–8 min per matrix leg |
| **smoke** | `docker compose up` → `GET /health` + `/openapi.json` | ~5–12 min |

**Total PR pipeline:** ~10–20 minutes (lint + test matrix run in parallel; smoke waits for both).

## Install commands (match CI locally)

```bash
# Lint
pip install ruff
ruff check api agents config tests storage processors validation_pipeline feedback telemetry scrapers

# Unit tests (same env vars CI uses)
export GEMINI_API_KEY=ci-fake-gemini-key GOOGLE_API_KEY=ci-fake-gemini-key API_AUTH_ENABLED=false
pytest -q

# Smoke (requires Docker)
./scripts/ci-smoke.sh
```

When issue #4 lockfile is on `main`, Python **3.12** installs from pinned `requirements.txt`;
Python **3.11** installs from `requirements.in` (source constraints).

## Merge gate

Enable in GitHub → **Settings → Branches → Branch protection rules** for `main`:

- [x] Require status checks to pass before merging
- Required checks: `Lint (ruff)`, `Test (Python 3.11)`, `Test (Python 3.12)`, `Docker Compose smoke`

Until branch protection is enabled, CI still runs and shows red/green on PRs but cannot block merges by itself.

## Flaky-test policy

1. **CI retries once** — the test job uses `nick-fields/retry` with `max_attempts: 2`.
2. **If a test fails twice**, treat it as a real failure — fix or quarantine the test in a follow-up PR; do not raise retry count without team agreement.
3. **No retry on lint or smoke** — those should be deterministic.
4. **Suspected flakes** — note in the PR description and link the failing run; if the same test flakes twice in a week, open an issue to fix root cause.

## Status badge

Add to README (already wired when workflow is on `main`):

```markdown
[![CI](https://github.com/intotheopen/intotheopen-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/intotheopen/intotheopen-backend/actions/workflows/ci.yml)
```
