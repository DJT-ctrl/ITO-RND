# Phase 10 — Test Document

**Scope:** T10.1–T10.11 (Agentic Layer)  
**Status of phase:** Complete  
**Companion:** [`Phase_10.md`](Phase_10.md) · production ops: [`../current md/10_PRODUCTION_RUNBOOK.md`](../current%20md/10_PRODUCTION_RUNBOOK.md)

Use this doc to verify Phase 10 after a PR, before merge, or on a staging host. It covers **automated pytest**, **local smoke**, **dashboard QA**, and **production tick** checks.

---

## Quick start

```bash
cd /path/to/repo
source .venv/bin/activate   # or your venv

# All Phase 10–related unit tests (no live Apify / Pro spend)
python -m pytest \
  tests/test_phase10_topics_and_weights.py \
  tests/test_phase10_scheduler_budget.py \
  tests/test_phase10_corpus_refresh.py \
  tests/test_phase10_pro_digest.py \
  tests/test_soft_topic_prefer.py \
  tests/test_feedback_routing.py \
  tests/test_feedback_retrieve.py \
  -q
```

Expect: all green. Failures here block merge.

---

## Prerequisites

| Need | For |
|------|-----|
| Python venv + `requirements` | Unit tests |
| `DATABASE_URL` | Smoke / dashboard / tick against real DB |
| `GEMINI_API_KEY` | Live Pro digest (skip if dry-run only) |
| `APIFY_API_TOKEN` + actor ids | Live scrape / validation (optional, costly) |
| Streamlit | Dashboard QA |

Safe defaults for live smoke:

```bash
# Prefer dry-run digests until you intend to spend Pro $
export AGENTIC_PRO_DIGEST_DRY_RUN=1
```

---

## Automated tests ↔ tasks

| Task | What it covers | Test file(s) |
|------|----------------|--------------|
| **T10.2 / T10.6** | Topic normalize, niche weights, tagging | `tests/test_phase10_topics_and_weights.py` |
| **T10.3 / T10.9** | Ledger, budget gate, tick skip/run | `tests/test_phase10_scheduler_budget.py` |
| **T10.4 / T10.5 / T10.5.5** | Niche queries, budgets, refresh, proof, handlers | `tests/test_phase10_corpus_refresh.py` |
| **T10.7** | Niche-prefixed clusters + fallback | `tests/test_feedback_routing.py`, `tests/test_feedback_retrieve.py` |
| **T10.8** | Soft topic prefer re-rank / over-fetch | `tests/test_soft_topic_prefer.py` |
| **T10.10** | Snapshot, critic parse, dry-run, tick digest, pricing | `tests/test_phase10_pro_digest.py` |
| **T10.1 / T10.11** | UI/runbook (manual) | Dashboard + ops sections below |

### Pass criteria (CI / local)

- [ ] Full Phase 10 pytest set above passes
- [ ] No new failures in related feedback/RAG suites

---

## Per-task checklist

### T10.1 — Agentic Layer dashboard

**Manual**

1. From [dashboard-for-devs](https://github.com/intotheopen/dashboard-for-devs): `streamlit run dashboard/app.py` (backend installed editable)
2. Open **Agentic → Agentic layer**
3. Confirm panels render: seeds, plan, flags, schedule, budget, scrape proof, Pro digests
4. Edit seed terms → save → reload page → values persist
5. Toggle a job flag → save → reload → flag sticks
6. Captions mention tick / `ito-agentic-tick.timer` (not “not implemented”)

**Pass**

- [ ] Page loads without exception
- [ ] Seeds + flags persist across refresh

---

### T10.2 — Search plan

**Automated:** topics/weights tests.

**Manual / smoke**

```bash
python - <<'PY'
from config.settings import load_settings
from phase_10.search_plan import get_search_plan, rebuild_search_plan
s = load_settings()
plan = get_search_plan(s)
print("terms", len(plan.terms), "weights", plan.weights_by_niche, "stub", plan.stub)
# Optional: rebuild_search_plan(s)
PY
```

On dashboard: **Rebuild plan** → weights update from `user_niches` (empty OK if no tagged subscriber posts).

**Pass**

- [ ] Plan loads without error
- [ ] Seed account URLs editable; plan shows terms + weights (or empty weights)

---

### T10.3 — Scheduler + budget gate

**Automated:** `test_phase10_scheduler_budget.py`.

**Smoke (no paid scrapes if flags off)**

```bash
# Disable scrapes/digest via Agentic flags UI first, or expect skips
python -m phase_10.jobs.run_agentic_tick -v
```

Check output lines for each job: `ran` or `skipped: …`.

**Pass**

- [ ] Disabled jobs → `skipped: disabled`
- [ ] Not-due jobs → `skipped: not due`
- [ ] Over-cap jobs → `skipped:` with cap reason (force via low `AGENTIC_*_DAILY_CAP_USD` in a test env if needed)
- [ ] Schedule panel shows updated `last_result`

---

### T10.4 / T10.5 — Corpus refresh

**Automated:** corpus refresh unit tests (mocked Apify).

**Live (optional — costs Apify $)**

1. Enable `general_refresh` and/or `niche_scrape`
2. Ensure seed terms (and for niche: non-empty weights)
3. Run tick or wait for due interval
4. Confirm posts land with `posts.niche` set where forced
5. Ledger / budget panel shows Apify spend attributed to `general_refresh` / `niche_scrape`

**Pass (unit)**

- [ ] Pytest green
- [ ] Handlers registered: `general_refresh`, `niche_scrape`, `pro_digest` in `HANDLERS`; none in `STUB_REASONS`

**Pass (live)**

- [ ] Proof row written; corpus grew or skip reason is intentional (idle/fresh/budget)

---

### T10.5.5 — Scrape proof

**Manual**

1. After a refresh run, open **Scrape proof** panel
2. Confirm fields: queries, new vs already-in-DB, niche, Apify USD, overlap/waste when present

**Pass**

- [ ] Latest proof visible and `ok` / summary readable
- [ ] Tick `last_result` one-liner matches run outcome

---

### T10.6 — Topic taxonomy + tagging

**Automated:** `test_phase10_topics_and_weights.py`.

**Optional backfill**

```bash
python -m phase_10.backfill_niches
```

**Pass**

- [ ] Known aliases map to enum niches
- [ ] All-fintech users → sports (etc.) absent from weights

---

### T10.7 — Topic on feedback buckets

**Automated:** routing + retrieve tests (niche prefix, underscored niches, fallback).

**Manual spot-check**

1. Validate a post with known `posts.niche`
2. Confirm feedback / cluster id looks like `{niche}_{length}_{format}_{followers}` when niche known
3. Sparse niche still returns lessons via shape/global fallback (no hard empty)

**Pass**

- [ ] Pytest green
- [ ] Legacy shape-only cluster ids still resolve

---

### T10.8 — Soft topic prefer (RAG)

**Automated:** `tests/test_soft_topic_prefer.py`.

**Pass**

- [ ] Same-niche neighbors sort first without dropping others
- [ ] `prefer_niche=None` preserves distance order
- [ ] Over-fetch then truncate when soft prefer on

---

### T10.9 — Cost ledger

**Automated:** ledger upsert / gate / snapshot tests.

**Manual**

1. Agentic **Budget** panel shows daily/monthly Apify + Gemini used vs caps
2. After a paid job, used amount increases
3. With cap set below used, next paid job skips

**Pass**

- [ ] Caps from env match panel
- [ ] Skip reason mentions daily or monthly cap

---

### T10.10 — Pro workflow digest

**Automated:** `tests/test_phase10_pro_digest.py`.

**Smoke (recommended — dry-run, no Pro $)**

```bash
export AGENTIC_PRO_DIGEST_DRY_RUN=1
python - <<'PY'
from dataclasses import replace
from config.settings import load_settings
from phase_10.digests import list_digests, run_pro_digest
s = replace(load_settings(), agentic_pro_digest_dry_run=True)
print(run_pro_digest(s))
for d in list_digests(s, limit=3):
    print(d.created_at, d.severity, d.model, len(d.payload.get("findings") or []))
PY
```

**Live Pro (optional — spends Gemini 3.1 Pro)**

1. `AGENTIC_PRO_DIGEST_DRY_RUN=0` (or unset)
2. Enable `pro_digest` flag **or** click **Run digest now** on Agentic tab
3. Confirm budget gate allows Gemini
4. Digest appears with severity + findings table
5. Gemini spend attributed to `pro_digest`

**Pass**

- [ ] Dry-run writes a digest with `payload.dry_run` / zero spend
- [ ] Snapshot redacts seed account URLs (count only)
- [ ] Malformed model JSON falls back without crashing (unit)
- [ ] Tick can run `pro_digest` when enabled and due

---

### T10.11 — Production worker wiring

**Docs / units present**

- [ ] [`deploy/ito-agentic-tick.service`](../deploy/ito-agentic-tick.service)
- [ ] [`deploy/ito-agentic-tick.timer`](../deploy/ito-agentic-tick.timer)
- [ ] Runbook section *Phase 10 — Agentic Layer* in production runbook
- [ ] `deploy/README.md` documents install + cron fallback

**On Linux host (staging/prod)**

```bash
sudo cp deploy/ito-agentic-tick.service deploy/ito-agentic-tick.timer /etc/systemd/system/
# edit WorkingDirectory / EnvironmentFile if needed
sudo systemctl daemon-reload
sudo systemctl enable --now ito-agentic-tick.timer
systemctl list-timers | grep agentic
sudo systemctl start ito-agentic-tick.service   # one-shot now
journalctl -u ito-agentic-tick -n 50
```

**Pass**

- [ ] Timer listed; one-shot exits 0 (or 2 only if a job truly failed)
- [ ] Agentic Schedule updates `last_run_at` / `last_result`
- [ ] **No** parallel crons for `run_validation_worker` / `run_feedback_worker` alongside the tick

---

## End-to-end smoke matrix

| Scenario | Cost | Steps | Expected |
|----------|------|-------|----------|
| A. Unit only | $0 | pytest set above | All pass |
| B. Tick dry | $0–small | Flags: val+fb on, scrapes off, digest dry-run; run tick | Handlers run/skip cleanly; schedule updates |
| C. Digest dry | $0 | `run_pro_digest` dry-run | Row in `agentic_digests`; UI lists it |
| D. Digest live | cents | Disable dry-run; Run digest now | Structured findings; Gemini ledger bump |
| E. Scrape live | Apify $ | Enable general refresh; run when due | Proof + posts + Apify ledger |
| F. Prod timer | as configured | Enable systemd timer | Recurring schedule updates |

Recommended merge gate: **A + B + C**.  
Recommended staging gate before prod: **A–C**, then **F**.  
**D / E** when intentionally validating paid paths.

---

## Regression / safety

- [ ] Product Flash path unchanged (`AGENT_GEMINI_MODEL` / flash-lite for eval/predict)
- [ ] Pro only used for digests (`AGENTIC_PRO_DIGEST_MODEL`)
- [ ] Digests are read-only (no auto flag/seed/prompt mutation)
- [ ] Budget gate blocks over-cap Apify and Gemini jobs
- [ ] Seed LinkedIn URLs not sent into Pro snapshot (count only)
- [ ] Soft RAG never hard-filters to niche-only empty results

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Tick `aborted: DATABASE_URL…` | Missing DB | Set `DATABASE_URL` |
| Always `skipped: not due` | Interval not elapsed | Clear `next_run_at` in `agentic_job_runs` or wait; or adjust `AGENTIC_*_INTERVAL_HOURS` |
| `skipped: disabled` | Job flag off | Enable on Agentic flags panel |
| Digest fails: API key | No Gemini key | Set `GEMINI_API_KEY` |
| Digest spends $0 unexpectedly | Dry-run on | Unset `AGENTIC_PRO_DIGEST_DRY_RUN` |
| Scrape no-ops | Empty seeds / idle niches / budget | Check plan weights, caps, proofs |
| Double Apify spend | Parallel validation cron + tick | Remove standalone worker cron (T10.11) |

---

## Sign-off

| Gate | Owner | Date | Result |
|------|-------|------|--------|
| Unit pytest (A) | | | |
| Tick smoke (B) | | | |
| Digest dry-run (C) | | | |
| Dashboard T10.1 panels | | | |
| Staging timer (F) | | | |
| Live Pro / scrape (D/E) optional | | | |

**Phase 10 ready for merge / prod:** ☐ Yes · ☐ No (notes: __________)
