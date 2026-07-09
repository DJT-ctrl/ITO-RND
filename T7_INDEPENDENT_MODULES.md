# T7 Independent Modules — Brainstorm
**Date:** 2026-07-08
**Status:** Planning / Brainstorm
**Context:** Net-new modules and pipelines that stand alone from the existing evaluation cycle. These are not changes to T1–T3.4 — they are additive surfaces that can be scoped, built, and run independently.

---

## A. Independent Data-Side Pipelines
*Run on a schedule, write to their own tables. Zero coupling to the live request path.*

### A1 — Anomaly Post-Mortem Agent
**What it does:** Runs over posts already flagged with `engagement_anomaly_flag = TRUE` in the database and writes a short "why did this over/under-perform" explanation for each one.

**Why it matters:** `engagement_anomaly_flag` and `anomaly_reasons` are already computed by `processors/benchmark.py` and stored in `storage/schema.sql` — but nothing currently consumes them. This agent turns discarded outliers into a curated library of real viral/flop case studies, which later becomes grounding material for the SEO and Predictor agents.

**Independence:** Fully offline batch job. No user-facing request path. Reads from `posts`, writes to a new `post_mortems` table.

**Feasibility:** High. All required input data already exists in the database today.

---

### A2 — Trend Radar / Topic-Drift Monitor
**What it does:** A scheduled job that clusters the existing 3072-dim embedding corpus and tracks which topic clusters are growing week-over-week. Output: a `trends` table with cluster labels and growth signals.

**Why it matters:** This is the most accurate signal for *LinkedIn-specific* discoverability — built from your own scraped corpus rather than generic Google results. The grounded SEO agent (T6.4) should lean on this table as its primary source of what's trending on LinkedIn.

**Independence:** Reads from the `posts` embedding column via pgvector. Writes to a `trends` table. Runs on a schedule independent of any user session.

**Feasibility:** High. The embeddings and pgvector index already exist in `data/embeddings/` and the database.

---

### A3 — Comment / Reaction Mining Pipeline
**What it does:** A standalone pipeline that pulls comment text and reaction breakdowns from scraped posts (the Apify actor already supports this — noted in `First Ideas/Scraper_infomation.md`) and mines them for recurring questions, objections, and high-signal phrases.

**Why it matters:** Comment text is the audience telling you exactly what they want more of. This is a content-idea source derived directly from real audience responses, not model assumptions.

**Independence:** Separate scraper run + NLP pass. Writes to its own `comments` table. No dependency on the evaluation cycle.

**Feasibility:** Medium. Requires enabling the comments/reactions output in the Apify actor config and writing a lightweight NLP pass (keyword extraction / clustering).

---

### A4 — Engagement-Decay Capture Job
**What it does:** Re-scrapes a sample of posts at fixed intervals (e.g. 24h, 48h, 7d after publish) to measure how engagement accrues over time per post.

**Why it matters:** Directly de-risks the feedback loop (T6 Engineering Gaps #1) by establishing *when* it is fair to grade a prediction. Without knowing the engagement decay curve, there is no principled way to set the re-scrape window for backtesting.

**Independence:** Scheduled batch job. Writes timestamped engagement snapshots to a `post_engagement_history` table.

**Feasibility:** Medium. Requires tracking original publish timestamps and scheduling follow-up scrape runs.

---

## B. New Generative Agents
*The inverse of the existing pipeline — these create from scratch rather than evaluate a draft.*

### B1 — Content Ideation Agent
**What it does:** Takes a user's `voice_profile` (already modelled in `agents/schemas.py`) + Trend Radar output (A2) + their top past posts and generates fresh post *ideas* before any draft exists.

**Why it matters:** The entire current pipeline assumes the user already has a draft. This agent fills the step before that — turning the product from "editor" into "creative partner."

**Independence:** Separate agent endpoint. Reads from `voice_profile` and `trends`. No dependency on the evaluation cycle.

**Feasibility:** High once A2 exists. `voice_profile` data structure is already defined.

---

### B2 — Posting-Time Optimizer
**What it does:** A pure stats module (no LLM) that recommends the optimal posting window per user and topic, based on `hour_of_day` and `day_of_week` already stored on every post in the database.

**Why it matters:** Zero API cost, fully deterministic, and the data to power it is already there. This is one of the highest-value / lowest-cost additions on the list.

**Independence:** Completely standalone. Reads from `posts`, returns a recommendation. No LLM, no external API.

**Feasibility:** High. All required data already exists in the database today.

---

### B3 — Repurposing Agent
**What it does:** Takes input from entirely *outside* the system — a blog post URL, a talk transcript, a thread — and slices it into a LinkedIn post series, each scored through the existing evaluation cycle.

**Why it matters:** Widens the top-of-funnel beyond users who already have a draft. Users who produce long-form content elsewhere get immediate LinkedIn-optimised cuts without starting from scratch.

**Independence:** New ingestion endpoint + evaluation cycle call. The evaluation cycle is reused, not changed.

**Feasibility:** Medium. Requires a document ingestion step (URL fetch / PDF parse) upstream of the existing pipeline.

---

## C. Measurement and Evaluation Systems
*Offline harnesses that protect the system as agents and models change.*

### C1 — Backtesting / Calibration Harness
**What it does:** Replays historical posts through the Predictor Agent and measures how well `predicted_engagement_percentile` tracks the real `engagement_percentile` already stored in the database.

**Why it matters:** This is the quantitative proof-of-value the team currently has none of. Without it, there is no hard evidence the system's predictions are meaningful — just qualitative impressions.

**Independence:** Fully offline. No user. Reads from `posts`, writes calibration results to a `backtest_runs` table.

**Feasibility:** High. All required data already exists. The Predictor Agent is already built.

---

### C2 — Golden-Set Regression Suite
**What it does:** A fixed set of known drafts with expected score ranges. Runs automatically when the model or prompt changes to catch drift before it ships.

**Why it matters:** `DEFAULT_MODEL = "google-gla:gemini-2.5-flash"` is hardcoded in every agent file. When that model is swapped for a newer version, the scores will shift. Without a golden set, the team won't know by how much until users notice.

**Independence:** Offline test harness. Part of CI, not the request path.

**Feasibility:** High. Requires curating 10–20 representative drafts and documenting their expected score ranges.

---

### C3 — Model Bake-Off Harness
**What it does:** Runs the same golden-set drafts across multiple models (flash vs. pro vs. alternatives) and produces a cost/quality comparison table.

**Why it matters:** Pairs directly with the cost/latency observability gap (T6 Engineering Gaps #5). Gives the team a principled basis for model selection decisions rather than defaulting to whatever is newest.

**Independence:** Offline. Builds on top of C2.

**Feasibility:** Medium. Depends on C2 (golden set) existing first.

---

## D. Adjacent / External Surfaces
*Strategic expansions and new product surfaces. Architecturally grounded, higher effort.*

### D1 — Multi-Platform Expansion
**What it does:** Extends the full T1–T3 pipeline to X/Twitter, Threads, Instagram, or other platforms.

**Why it matters:** The schema and scrapers are already platform-tagged (`platform_name` field). The embedding, database, and agent layers are platform-agnostic. Adding a new platform is: new scraper + re-embed + re-ingest. Everything downstream reuses without modification.

**Independence:** New scrapers per platform. The rest of the stack is unchanged.

**Feasibility:** Medium per platform. Architecturally the cheapest multi-platform expansion possible given how the system was designed.

---

### D2 — Browser-Composer Overlay (Chrome Extension)
**What it does:** A Chrome extension that calls the existing FastAPI endpoint to score a draft *inside LinkedIn's actual composer* — without leaving the platform.

**Why it matters:** The API contract (T2.3) and OpenAPI spec already exist. This is pure frontend glue. Users get scores in context, at the moment they are writing, not in a separate tool.

**Independence:** Entirely frontend. Zero backend changes. The FastAPI endpoint is already live.

**Feasibility:** Medium. Chrome extension development is a separate skillset, but the backend is already done.

---

### D3 — Voice-Fingerprint Onboarding Pipeline
**What it does:** A standalone onboarding flow for new subscribers: scrape their last N public posts, build their `voice_profile` and personal engagement benchmark, and populate their profile before they ever submit a draft.

**Why it matters:** `get_user_voice_profile()` already exists in `storage/vector_store.py` and the personalization logic is wired into every agent. But there is no *population path* for a brand-new user. Without this, personalization is only available after weeks of use — cold-start problem.

**Independence:** Standalone onboarding pipeline. Reads from LinkedIn via profile scraper, writes to `posts` table with `user_id` set. No dependency on the evaluation cycle.

**Feasibility:** High. All required components already exist: profile scraper, embedding pipeline, DB schema with `user_id` scoping.

---

### D4 — Weekly Digest Agent
**What it does:** A scheduled agent that composes a "what's trending in your niche + how your posts performed" digest, delivered via email or Slack.

**Why it matters:** Turns a request/response tool into a retention-driving product. Users engage with the system weekly even when they are not actively drafting a post.

**Independence:** Scheduled job. Reads from `trends` (A2) + `post_engagement_history` (A4) + `predictions` table (feedback loop). Writes to an outbound email/Slack integration.

**Feasibility:** Medium. Depends on A2 and the feedback loop (T6 Engineering Gaps #1) being in place first.

---

## Priority Summary

| Module | Effort | Value | Depends on | Recommended start? |
|--------|--------|-------|------------|-------------------|
| A1 Anomaly Post-Mortem | Low | High | Nothing — data exists today | Yes |
| B2 Posting-Time Optimizer | Low | High | Nothing — data exists today | Yes |
| C1 Backtesting Harness | Low | High | Nothing | Yes |
| D3 Voice Onboarding Pipeline | Low-Medium | High | Existing scraper + schema | Yes |
| A2 Trend Radar | Medium | High | Embedding corpus | Next |
| D1 Multi-Platform | Medium | Very High | New scrapers only | Next |
| C2 Golden-Set Regression | Low | Medium | Curation effort | Next |
| A3 Comment Mining | Medium | Medium | Apify config | Later |
| A4 Engagement-Decay | Medium | Medium | Scheduling infra | Later |
| B1 Ideation Agent | Medium | High | A2 (Trend Radar) | Later |
| D2 Chrome Extension | High | High | FastAPI (done) | Later |
| B3 Repurposing Agent | Medium | Medium | Ingestion step | Later |
| C3 Model Bake-Off | Low | Medium | C2 (Golden Set) | Later |
| D4 Weekly Digest | Medium | High | A2 + feedback loop | Later |
