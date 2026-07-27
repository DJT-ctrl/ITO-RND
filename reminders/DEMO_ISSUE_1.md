# Demo fix — Issue #1 (agent provider initialization)

**Status:** Local demo on branch `fix/issue-1-agent-provider-init`  
**Issue:** [intotheopen/intotheopen-backend#1](https://github.com/intotheopen/intotheopen-backend/issues/1)  
**Not committed / not PR'd yet** — waiting for your go-ahead.

---

## What the issue asked for

| Acceptance criterion | How this demo addresses it |
| -------------------- | -------------------------- |
| `pytest` must not fail during module import | Provider string is pure formatting; agents not built at import |
| API startup fails gracefully with clear guidance | `/health` always up; `/evaluate` returns **503** with config text if agents can't build |
| Unit tests cover model/provider normalization | New `tests/test_pydantic_ai_model.py` |

---

## What changed (code)

### 1. `config/settings.py`
- **Before:** tried `google:` then **fell back to `google-gla:`** when `infer_model` failed → on pydantic-ai 2.x that becomes `Unknown provider: google-gla`.
- **After:** always normalize to `google:…`. Legacy `google-gla:` env values are rewritten.
- Added `validate_agent_model()` for optional hard checks **at use time**, not import time.

### 2. `api/main.py`
- **Before:** built predictor + diagnostic agents at module import (lines that ran before the app existed).
- **After:** `_ensure_eval_agents()` builds them on first `/evaluate` only.
- `/health` and `/api/v1/similar-posts` no longer depend on agent init.

### 3. `tests/test_pydantic_ai_model.py`
- Normalization cases (`None`, bare id, `google:`, `google-gla:`)
- Assert never returns `google-gla:`
- Assert `api.main` import leaves agents as `None` and `/health` works

### Not changed (on purpose — ask you)
- Dashboard Evaluation Cycle page still builds agents at page load — same smell, separate follow-up?
- Local venv may still be pydantic-ai **0.8.1**; `requirements.txt` wants **>=2.5**. Aligning the env is a separate step.

---

## How to verify locally

```bash
git checkout fix/issue-1-agent-provider-init
source .venv/bin/activate
pytest tests/test_pydantic_ai_model.py tests/test_api.py -q
```

Optional smoke:

```bash
python -c "import api.main; print(api.main.predictor_agent)"  # expect None
```

---

## Suggested PR text (when you approve)

**Title:** `fix(agents): lazy-init provider to avoid import crash (#1)`

```markdown
Closes #1

## Summary
- Normalize Gemini model ids to `google:` (no `google-gla:` fallback)
- Build predictor/diagnostic agents on first `/evaluate`, not at import
- Add unit tests for provider normalization and import-safe API load

## How to test
- [ ] `pytest tests/test_pydantic_ai_model.py tests/test_api.py -q`
- [ ] `GET /health` returns ok without agents initialized
- [ ] `/evaluate` returns 503 with clear message if provider init fails

## Risks / rollback
- First `/evaluate` pays a one-time agent build cost
- Revert this PR if dashboard/API behavior regresses; no schema migrations
```

(No `Made with Cursor` footer — omit editor watermarks from PR text.)

---

## Questions for you

1. **Commit + open PR** against `intotheopen/intotheopen-backend` (or only `DJT-ctrl/ITO-RND`)?
2. **Include dashboard lazy-init** in this PR, or leave for a follow-up issue?
3. **Bump / reinstall** local venv to `pydantic-ai-slim[google]>=2.5` as part of this work?
4. Your other WIP is stashed as `wip before issue-1 demo` on `feat/new-ui` — restore that after, or keep this branch only?
