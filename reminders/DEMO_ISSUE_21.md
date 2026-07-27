# Demo fix — Issue #21 (load testing and performance baseline)

**Status:** Implementation on branch `feature/issue-21-load-baseline`  
**Issue:** [intotheopen/intotheopen-backend#21](https://github.com/intotheopen/intotheopen-backend/issues/21)  
**Backlog:** [`reminders/ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) (requirements section for #21)

---

## What the issue asked for

| Acceptance criterion | How this addresses it |
| -------------------- | --------------------- |
| Reproducible load test scripts exist | `scripts/load/run_load_test.py` + `scenarios.yaml` + `stub_api.py` |
| Baseline performance report is published | `docs/ops/LOAD_BASELINE.md` (stub lab numbers + live TBD) |
| Improvement plan with measurable targets | Next-release p95/RPS table; feeds **#22** |

---

## How to verify locally

```bash
source .venv/bin/activate
pytest tests/test_load_baseline.py -q

python scripts/load/stub_api.py &
python scripts/load/run_load_test.py --scenario baseline --base-url http://127.0.0.1:8010
```

---

## Suggested PR text

**Title:** `test(perf): add load scenarios and performance baseline (#21)`

```markdown
Closes #21

## Summary
- Add reproducible HTTP load scripts for /health, /similar-posts, and /evaluate
- Publish docs/ops/LOAD_BASELINE.md with hot-path bottlenecks and next-release targets
- Document #21 requirements in reminders/ISSUE_BACKLOG.md

## How to test
- [ ] `pytest tests/test_load_baseline.py -q`
- [ ] Stub smoke: `python scripts/load/stub_api.py` + `run_load_test.py --scenario smoke --base-url http://127.0.0.1:8010`
- [ ] Read `docs/ops/LOAD_BASELINE.md` targets vs #22

## Risks / rollback
- Scripts are opt-in; no runtime API behavior change
- Stub delays are synthetic — replace live TBD table after staging run
```
