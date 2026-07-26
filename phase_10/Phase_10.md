# Phase 10 — Agentic Layer (Background Automation)

**Status:** In progress (T10.10 Pro digest done; T10.11 worker runbook next)  
**Owner (sheet):** TBD (diagram: Erdal agentic layer)  
**Folder:** [`phase_10/`](.)  
**Models:**
- Product path (eval, diagnostics, variants, hybrid feedback): Gemini Flash / `gemini-2.5-flash-lite` via `AGENT_GEMINI_MODEL`
- Meta “dev AI” digest only: **Gemini 3.1 Pro** (`gemini-3.1-pro-preview` via `AGENTIC_PRO_DIGEST_MODEL`)

**Principle:** Do **not** remake scrape / analyse / embed / validate / feedback / eval. New code is thin: **search plan + scheduler + budget gate + topic routing + Pro digest + Agentic Layer tab** that **calls** existing modules.

**Related (already built):**
- Scrapers: [`scrapers/`](../scrapers/)
- Processors / collection: [`processors/`](../processors/)
- Validation: [`validation_pipeline/`](../validation_pipeline/)
- Feedback loop: [`feedback/`](../feedback/)
- Telemetry / cost: [`telemetry/`](../telemetry/)
- Live eval cycle: [`agents/orchestrator.py`](../agents/orchestrator.py)
- Dashboard pages 1–10 under [`dashboard/pages/`](../dashboard/pages/)

**Related phases:**
- [Phase 7](../Phase_7.md) — on-demand multi-agent evaluation (T7.1–T7.16)
- Phase 8 — feedback loop (learn from real outcomes)
- Phase 9 — independent offline modules (A1–A4)

---

## What this phase is

Turn the diagram hub **“Automated feedback system first proposed (agentics)”** into a **scheduled, cost-gated background layer**:

1. Keep the corpus fresh (general scrape on a timer).
2. Adapt scrape targets from **seed terms/accounts**, then **user niches** (so a fintech-only user base does not keep scraping sports).
3. Add a **topic** dimension to feedback buckets.
4. Keep **one global RAG** with optional soft topic preference (no separate niche vector index).
5. Run a daily **Pro** “dev AI” that reads logs/telemetry and suggests what to change (read-only first).
6. Expose ops controls in a new dashboard tab: **Agentic Layer**.

Not an always-on LLM. Jobs on a schedule; Flash for product; Pro for the meta digest only.

---

## Background pipeline

```mermaid
flowchart TB
  Seed[Seed terms + seed accounts] --> Plan[Search Plan]
  Users[User niches from signups/posts] --> Plan
  Plan --> Gen[General scrape ~3h]
  Plan --> Niche[Niche scrape daily]
  Gen --> Corpus[Shared corpus + topic tags]
  Niche --> Corpus
  Corpus --> Embed[Existing analyse/embed]
  Embed --> RAG[Global RAG + soft topic prefer]
  Embed --> FB[Feedback buckets + topic dim]
  Tick[Scheduler + budget gate] --> Gen
  Tick --> Niche
  Tick --> Workers[Existing validation/feedback workers]
  Logs[Telemetry + run logs] --> DevAI[Pro daily digest]
```

---

## Design locks

| Decision | Choice |
|----------|--------|
| Always-on LLM | **No** — scheduled jobs only |
| Cadence | General **~every 3 hours**; niche **daily**; Pro digest **daily** |
| Models | Flash = product path; **Gemini 3.1 Pro = T10.10 only** |
| Niche RAG | **No** separate niche index; soft topic prefer (T10.8) |
| What dictates search | Seed terms/accounts **then** user-derived plan (T10.2) |
| Multi-instance per user type | **No** — one worker pool, niche-keyed jobs |
| UI | New **Agentic Layer** tab (T10.1); call existing code |
| Code reuse | Thin wrappers / jobs; no forked scrape or eval pipelines |

---

## Task index

| ID | Name | Status | Depends on | Notes |
|----|------|--------|------------|-------|
| **T10.1** | Agentic Layer Dashboard Tab | **Done** | T10.2, T10.3, T10.9, T10.10 | UI live; plan/schedule/budget/proof/digests |
| **T10.2** | Search Plan Service | **Done** | T10.6 (for weights) | Postgres `agentic_search_plan` + rebuild |
| **T10.3** | Scheduler + Budget Gate | **Done** | T10.9 | Tick CLI + run state |
| **T10.4** | General Corpus Refresh Job | **Done** | T10.2, T10.3 | Shared spine; seed terms |
| **T10.5** | Niche Scrape Job (demand-driven) | **Done** | T10.2, T10.3, T10.6 | Alias queries; force niche; idle/stale skip |
| **T10.5.5** | Scrape Proof / Run Health | **Done** | T10.4, T10.5 | Multi-signal proof + Agentic panel (not a cron) |
| **T10.6** | Topic Taxonomy + Tagging | **Done** | — | Enum + `posts.niche` + `user_niches` |
| **T10.7** | Topic Dimension on Feedback Buckets | **Done** | T10.6 | Extend `feedback/routing.py` + fallback |
| **T10.8** | Soft Topic Preference in RAG | **Done** | T10.6 | Global `find_similar` only |
| **T10.9** | Cost Control Ledger | **Done** | — | Caps + gate + `agentic_cost_ledger` |
| **T10.10** | Dev AI Workflow Critic (Pro) | **Done** | T10.3, T10.9 | Structured digests + tick handler |
| **T10.11** | Worker Wiring (validation + feedback) | Planning | T10.3 | Runbook cron/systemd; tick already calls workers |

**Counts:** Planning 1 · Partial 0 · Done 11.

---

## Sheet rows (tracker copy-paste)

| Phase | ID | Name | Owner | Description | Acceptance / outputs | Stack | Status |
|-------|-----|------|-------|-------------|----------------------|-------|--------|
| Phase 10 | **T10.1** | Agentic Layer Dashboard Tab | TBD | New Streamlit page **Agentic Layer**: configure seed search terms + seed accounts, view derived search plan / niche weights, budget used, last/next runs, start-stop flags, Pro digests. Ops UI only — no duplicated scrape/eval logic. | Tab live under dashboard; all actions call shared services/jobs; shows plan, runs, costs, digests. | Streamlit / Python | **Done** |
| Phase 10 | **T10.2** | Search Plan Service | TBD | Single source of truth for “what do we scrape?”. Layers: (1) operator **seed terms**, (2) optional **seed LinkedIn accounts** (bootstrap / simulate), (3) **user-derived niche weights** from signed-up users’ posts. If all users are fintech, sports weight → 0 (or absent). | Persisted `search_plan` (terms, weights, niche ids, updated_at); helpers to read plan for jobs; seed editable from T10.1. | Python / PostgreSQL | **Done** |
| Phase 10 | **T10.3** | Scheduler + Budget Gate | TBD | Cron/systemd (or worker tick): **~every 3h** general refresh; **daily** niche refresh for niches with demand / active users; optionally tick existing validation + feedback workers. **Not** always-on LLM. Before each paid step, enforce daily/monthly Apify + Gemini ceilings; priority: validation rescrape > niche (active) > general. | Jobs enqueue only when under budget; skipped runs logged with reason; schedule intervals configurable. | Python / Linux Cron / PostgreSQL | **Done** |
| Phase 10 | **T10.4** | General Corpus Refresh Job | TBD | Thin job: load search plan → call **existing** Apify post scrape + collection/analyse/embed path. Dedup / staleness so “newest” is incremental, not full re-scrape. | Posts land in shared corpus with topic tags; telemetry + Apify cost recorded; reuses `scrapers/` + processors (no fork). | Python / Apify / PostgreSQL | **Done** |
| Phase 10 | **T10.5** | Niche Scrape Job (demand-driven) | TBD | Daily: for each niche with user demand (or simulate weights), scrape niche keywords into shared corpus **tagged by topic**. Per active user = ensure their niche refreshed, **not** one AI process per user. | Niche-tagged posts ingested; idle niches skipped; cost attributable per niche in telemetry. | Python / Apify / PostgreSQL | **Done** |
| Phase 10 | **T10.5.5** | Scrape Proof / Run Health | TBD | Multi-signal proof artifact after each T10.4/T10.5 run (intent, yield, mix, freshness, cost, waste). Persist + show on Agentic Layer. **Not** a third cron. | Proof rows in DB; panel on Agentic tab; tick last_result one-liner. | Python / PostgreSQL / Streamlit | **Done** |
| Phase 10 | **T10.6** | Topic Taxonomy + Tagging | TBD | Coarse topic set (~8–12: e.g. sports, saas_b2b, fintech, creator, finance, health, career, marketing, other). Tag posts at analyse/ingest; infer **user niche profile** from their posts for T10.2 weights. Reuse analyser `topic` where present. | Stable topic enum; posts tagged; `user_niches` (or similar) drives plan weights. | Python / PostgreSQL | **Done** |
| Phase 10 | **T10.7** | Topic Dimension on Feedback Buckets | TBD | Extend `feedback/routing.py` metadata cluster from `{length}_{format}_{followers}` → `{topic}_{length}_{format}_{followers}`. Fallback when N &lt; `validation_cluster_n_min`: topic+shape → shape-only → global. Update labels / centroid path so Phase H does not break. | New cluster ids in feedback store; sparse niches still get lessons via fallback; tests for routing + fallback. | Python / PostgreSQL | **Done** |
| Phase 10 | **T10.8** | Soft Topic Preference in RAG | TBD | Keep **one global** `find_similar`. Optional re-rank / mix: prefer same-topic neighbors when available; **never** hard-filter to niche-only index (avoids cold-start / thin buckets). | Eval neighbors can bias to topic without separate niche vector DB; empty niche → pure global. | Python / pgvector | **Done** |
| Phase 10 | **T10.9** | Cost Control Ledger | TBD | Persist daily Apify + Gemini spend for agentic jobs; wire caps into T10.3. Reuse `telemetry/` pricing helpers; extend caps beyond feedback-LLM-only. | Dashboard shows spend vs cap; jobs no-op when over budget; warnings in digests. | Python / PostgreSQL | **Done** |
| Phase 10 | **T10.10** | Dev AI Workflow Critic (Pro) | TBD | Scheduled **daily** meta-agent: read telemetry, scrape-plan stats, validation MAE, feedback queue, errors. **Gemini 3.1 Pro only**. Output: structured digest of what might need changing (config, keywords, caps, failing niches). Read-only first — no auto-mutate prompts/flags. | Digest stored + shown on Agentic Layer tab; uses Pro; Flash unchanged for product agents. | Python / Gemini Pro / PostgreSQL | **Done** |
| Phase 10 | **T10.11** | Worker Wiring (reuse validation + feedback) | TBD | Register existing `validation_pipeline` + `feedback` worker CLIs on the same scheduler so agentic layer is an automated working way of what we already have, not a parallel loop. | Cron / job runner invokes existing CLIs; runbook updated; no duplicated validate/learn logic. | Python / Linux Cron | Planning |

---

## Task briefs

### T10.1 — Agentic Layer Dashboard Tab

**Status:** Done

**What:** New Streamlit page named **Agentic Layer**. Control and observe the background system; do not reimplement scrapers or eval.

**Surfaces:**
- Edit seed search terms and seed LinkedIn accounts
- View derived search plan (terms, niche weights, last updated)
- Budget used vs caps; last/next scheduled runs
- Start/stop or enable/disable job flags
- Latest Pro digests (T10.10) + **Run digest now**

**Do not:** Duplicate Scraper Stage / Evaluation Cycle logic — call shared services and job entrypoints.

**Shipped:**
- Nav: **Agentic → Agentic layer** via [`dashboard/app.py`](../dashboard/app.py) + [`dashboard/pages/11_Agentic_Layer.py`](../dashboard/pages/11_Agentic_Layer.py)
- Package: [`phase_10/`](.) — small modules (`search_plan`, `job_flags`, `budget`, `schedule`, `digests`) + [`phase_10/ui/`](ui/) panels
- Persist: seeds/weights in Postgres `agentic_search_plan` (JSON seeds migrated once); job flags still `data/agentic_job_flags.json`
- Contracts: frozen dataclasses in [`models.py`](models.py)
- Schedule + budget panels backed by T10.3 / T10.9
- Scrape proof panel (T10.5.5)
- Pro digests panel (T10.10): list + structured findings + manual run

---

### T10.2 — Search Plan Service

**Status:** Done

**What:** Answers “what should the scraper search?”

| Layer | Source | Role |
|-------|--------|------|
| 1. Seed | Operator (tab / config) | Bootstrap before real users |
| 2. Seed accounts | Operator LinkedIn URLs | Simulate / warm corpus |
| 3. User-derived | Signups + their posts → niches | Long-run mix; idle niches drop out |

**Shipped:**
- Table `agentic_search_plan` (singleton) + [`search_plan_store.py`](search_plan_store.py) / [`search_plan.py`](search_plan.py)
- `rebuild_search_plan()` → [`user_niches.refresh_user_niches`](user_niches.py) → global weights (primary niche per user)
- Job helpers: `queries_for_general_refresh`, `active_niches`, `seed_profile_urls`
- Agentic **Rebuild plan** button; empty weights when no subscriber-tagged posts

**Output shape:** `{ terms[], weights_by_niche{}, seed_accounts[], updated_at }` with `stub=False`.

---

### T10.3 — Scheduler + Budget Gate

**Status:** Done

**Cadence:**
- ~every **3 hours** — general corpus refresh (T10.4)
- **daily** — niche scrapes (T10.5)
- **daily** — Pro digest (T10.10)
- existing validation / feedback workers via tick (runbook polish = T10.11)

**Budget priority when near cap:** validation rescrape → active niche → general.

Skip + log when over daily/monthly Apify or Gemini ceilings (T10.9).

**Shipped:**
- Tick: `python -m phase_10.jobs.run_agentic_tick` ([`tick.py`](tick.py), [`jobs/run_agentic_tick.py`](jobs/run_agentic_tick.py))
- Run state: Postgres `agentic_job_runs` + [`schedule_store.py`](schedule_store.py); schedule panel live
- Honors [`job_flags`](job_flags.py); intervals via `AGENTIC_*_INTERVAL_HOURS`
- Real handlers: validation + feedback + general/niche corpus refresh + Pro digest

**Minimal cron example:**

```cron
*/15 * * * * cd /path/to/repo && .venv/bin/python -m phase_10.jobs.run_agentic_tick
```

(Full production cron/systemd examples → T10.11 / runbook.)

---

### T10.4 — General Corpus Refresh Job

**Status:** Done

Thin wrapper via shared spine [`corpus_refresh.py`](corpus_refresh.py): seed terms → Apify collect → **scoped** analyse/embed/ingest. Incremental (`sortBy=date`, small maxPosts, DB upsert). Records Apify spend (`agentic:general_refresh`). Writes T10.5.5 proof.

**Owns:** tick handler `general_refresh` (no longer stubbed).

---

### T10.5 — Niche Scrape Job (demand-driven)

**Status:** Done

Daily: `active_niches` → `queries_for_niche` (taxonomy aliases) → per-niche spine with `force_niche`. Weight-allocated post budget; skip idle / fresh niches (`AGENTIC_NICHE_STALE_HOURS`). Same scrape stack as T10.4.

**Owns:** tick handler `niche_scrape`; ledger attribution `agentic:niche_scrape`.

---

### T10.5.5 — Scrape Proof / Run Health

**Status:** Done

**Not a third cron.** Every T10.4/T10.5 run persists a multi-signal proof (`agentic_scrape_proofs`): queries, new vs already-in-DB, niche mix, freshness, Apify USD, overlap %, skips. Agentic **Scrape proof** panel lists latest runs. T10.10 may consume these later.

---

### T10.6 — Topic Taxonomy + Tagging

**Status:** Done

Coarse enum in [`topics.py`](topics.py) (~10 niches). Tag at analyse/finalize via [`tagging.apply_niche`](tagging.py) → `posts.niche` (free-text `topic` unchanged). Maintain `user_niches` for plan weights. Backfill: `python -m phase_10.backfill_niches`.

---

### T10.7 — Topic Dimension on Feedback Buckets

**Status:** Done

Today ([`feedback/routing.py`](../feedback/routing.py)):

`{length}_{format}_{followers}` → e.g. `medium_list_micro`

Target (when niche known):

`{topic}_{length}_{format}_{followers}` → e.g. `fintech_medium_list_micro`

**Shipped:**
- Optional `niche` on metadata / assign; null/invalid → legacy shape-only id (no rename of old lessons)
- Parsers handle underscored niches (`saas_b2b`, `ai_tech`); `cluster_label` updated
- Calibration + lesson fetch fallback: topic+shape → shape-only → global (`validation_cluster_n_min`)
- Niche plumbed via `CollectedPost.niche` + `posts.niche` lookup at predict/feedback generate

**Fallback when cluster N too low:** topic+shape → shape-only (current id) → global lessons.

---

### T10.8 — Soft Topic Preference in RAG

**Status:** Done

Keep a single pgvector index / `find_similar`. Soft re-rank same-topic neighbors. **Do not** build a niche-only RAG store (cold start and sparse niches hurt more than they help).

**Shipped:**
- Retrieval extracted to [`storage/similarity.py`](../storage/similarity.py) (T2.2 + T10.8 labels); re-exported from [`vector_store.py`](../storage/vector_store.py)
- Over-fetch ×3 (cap 50) + `apply_soft_topic_prefer` (same niche first, distance second); never hard-filters
- `SimilarPost.niche`; orchestrator / predict pass `prefer_niche` when known

---

### T10.9 — Cost Control Ledger

**Status:** Done

Track agentic Apify + Gemini spend per day/month. Caps feed T10.3. Surface on T10.1.

**Shipped:**
- Table `agentic_cost_ledger` + [`cost_ledger_store.py`](cost_ledger_store.py)
- Env caps: `AGENTIC_APIFY_DAILY_CAP_USD` / `MONTHLY`, `AGENTIC_GEMINI_*` (defaults $25/$500 Apify, $10/$200 Gemini)
- Gate: [`budget.allow_paid_step`](budget.py); snapshot + monthly metrics on Agentic Layer tab
- Attribution helper: `record_agentic_spend` + `agentic:<job_id>` context (call from T10.4 / T10.5 / T10.10 when those jobs spend)

---

### T10.10 — Dev AI Workflow Critic (Pro)

**Status:** Done

**Inputs:** budget, job runs, search plan (terms + weights; seed account **count** only), scrape proofs, validation MAE aggregates, feedback queue backlog, Apify telemetry, synthesized errors.  
**Output:** Postgres `agentic_digests` — structured findings + markdown summary (severity, category, evidence, suggested_action).  
**Model:** `gemini-3.1-pro-preview` (`AGENTIC_PRO_DIGEST_MODEL`); dry-run via `AGENTIC_PRO_DIGEST_DRY_RUN`.  
**Policy:** read-only — no auto-edits to prompts or feature flags. Dashboard only (no notify).

**Shipped:**
- Snapshot: [`digest_snapshot.py`](digest_snapshot.py)
- Critic: [`digest_critic.py`](digest_critic.py) (JSON mime + parse/normalize)
- Store: [`digest_store.py`](digest_store.py) + [`digests.py`](digests.py)
- Tick handler `pro_digest`; spend via `record_agentic_spend(..., provider="gemini")`
- Agentic digests panel: list findings + **Run digest now**

---

### T10.11 — Worker Wiring

Point the same scheduler at existing:

- `validation_pipeline/jobs/run_validation_worker.py` (and collect/predict as needed)
- `feedback/jobs/run_feedback_worker.py` (and related jobs)

**Note:** T10.3 tick already invokes validation + feedback workers when flags are on. This task owns production runbook cron/systemd examples and any collect/predict extras — not a parallel loop.

Document cron/systemd examples in the production runbook. No parallel validate/learn implementation.

---

## Suggested implement order

1. **T10.2 + T10.6** — plan + topics (defines what scrapes) **(done)**  
2. **T10.3 + T10.9** — schedule + budget (safe automation) **(done)**  
3. **T10.4 + T10.5 + T10.5.5** — corpus refresh + scrape proof **(done)**  
4. **T10.7 + T10.8** — topic in learn + soft RAG **(done)**  
5. **T10.1** — Agentic Layer tab to operate it **(done)**  
6. **T10.10** — Pro digest **(done)**  
7. **T10.11** — production cron/systemd runbook polish  

---

## Out of scope (later)

- Always-on / 24-7 LLM processes
- Separate agentic “instances” or servers per user type (revisit only if niche queues need different SLAs)
- Hard niche-only vector indexes
- Auto-mutating config from the Pro digest (phase after read-only digests prove useful)
- Other platforms / media types (diagram pink boxes) — same job interface later, new scrapers

---

## See also

| Doc / code | Role |
|------------|------|
| [Phase_7.md](../Phase_7.md) | On-demand eval agents |
| [`feedback/routing.py`](../feedback/routing.py) | Current shape-only clusters (extend in T10.7) |
| [`scrapers/linkedin_scraper.py`](../scrapers/linkedin_scraper.py) | Keyword scrape entry (reuse in T10.4/T10.5) |
| [`telemetry/`](../telemetry/) | Cost helpers (reuse in T10.9) |
| [`First Ideas/Complex_idea.md`](../First%20Ideas/Complex_idea.md) | Early general + personal niche bot vision |
