# Phase 9 — Independent Offline Modules

**Status:** Planning / partial implementation  
**Owner (sheet):** Ademola  
**Scope (current):** Only the four data-side modules below. Generative / measurement / adjacent ideas (old B1–D4, C1–C3) are **out of Phase 9** for now.

**Deep-dive folder:** [`phase_modules/`](phase_modules/README.md)  
**Historical name:** This backlog was once filed as “T7 Independent Modules” ([stub](T7_INDEPENDENT_MODULES.md)). Task IDs are now **T9.x**.

**Not to confuse with:** [Phase 7](Phase_7.md) (multi-agent evaluation) or [Phase 8](Phase_8.md) (feedback loop A–J).

---

## Modules

| ID | Module | Alias | Focused doc | Status |
|----|--------|-------|-------------|--------|
| **T9.1** | Anomaly Post-Mortem Agent | A1 | [phase_modules/A1_ANOMALY_POST_MORTEM.md](phase_modules/A1_ANOMALY_POST_MORTEM.md) | Implemented (v1) |
| **T9.5** | Trend Radar & Topic-Drift Monitor | A2 | [phase_modules/A2_TREND_RADAR.md](phase_modules/A2_TREND_RADAR.md) | Implemented (v1) |
| **T9.8** | Comment & Reaction Mining Engine | A3 | — (snapshot below) | Not started |
| **T9.9** | Engagement-Decay Tracking Service | A4 | — (snapshot below) | Not started |

**Considerations (not in the build table):**

| Topic | Doc | Notes |
|-------|-----|-------|
| Percentile extreme case studies | [CONSIDERATION_PERCENTILE_EXTREMES.md](phase_modules/CONSIDERATION_PERCENTILE_EXTREMES.md) | After / beside T9.1 — not the same as ratio anomalies |
| External popular-content trend tracker | [CONSIDERATION_EXTERNAL_TREND_TRACKER.md](phase_modules/CONSIDERATION_EXTERNAL_TREND_TRACKER.md) | After / beside T9.5 — keep separate from corpus radar |

Recommended order: **T9.1 → T9.5 → T9.8 → T9.9** (T9.1 and T9.5 already have v1).

---

## T9.1 — Anomaly Post-Mortem Agent (A1)

- **What:** Offline batch over `engagement_anomaly_flag = TRUE` → LLM post-mortem → `post_mortems` table.
- **Why offline:** Not on the live predict path; cron/CLI consumer of flags already set at finalize.
- **What is an anomaly:** Batch-relative **modified z-score > 3.5** on `comment_ratio` or `share_ratio` (not “top/bottom percentile” alone).
- **Run:** `python -m post_mortems.jobs.run_post_mortems --limit 50`
- **UI:** Check and learn → Special cases
- **Full note:** [A1_ANOMALY_POST_MORTEM.md](phase_modules/A1_ANOMALY_POST_MORTEM.md)

---

## T9.5 — Trend Radar & Topic-Drift Monitor (A2)

- **What:** Offline clustering of corpus embeddings → week-over-week growth → `trends` table (LinkedIn-shaped, scrape-relative).
- **Why it matters:** Complements neighbors/benchmarks; stronger LinkedIn signal than Google-only trends.
- **Run:** `python -m trend_radar.jobs.run_trend_radar --week YYYY-MM-DD`
- **UI:** Check and learn → Special cases (trends)
- **Full note:** [A2_TREND_RADAR.md](phase_modules/A2_TREND_RADAR.md)
- **External APIs:** Second radar later — [consideration](phase_modules/CONSIDERATION_EXTERNAL_TREND_TRACKER.md). On-demand Google Trends Tier 2 already exists for SEO.

---

## T9.8 — Comment & Reaction Mining Engine (A3)

**Status:** Not started  
**Independence:** Separate scraper run + NLP pass. Writes to its own `comments` (or equivalent) table. No dependency on the evaluation cycle.

**What it does:** Pull comment text and reaction breakdowns from scraped posts (Apify actor already supports this — see scraper notes) and mine recurring questions, objections, and high-signal phrases.

**Why it matters:** Comment text is the audience saying what they want more of — a content-idea source from real responses, not model assumptions.

**Feasibility:** Medium. Enable comments/reactions in Apify config + lightweight NLP (keyword extraction / clustering).

---

## T9.9 — Engagement-Decay Tracking Service (A4)

**Status:** Not started  
**Independence:** Scheduled batch job. Writes timestamped engagement snapshots to a `post_engagement_history` (or equivalent) table.

**What it does:** Re-scrape a sample of posts at fixed intervals (e.g. 24h, 48h, 7d after publish) to measure how engagement accrues over time.

**Why it matters:** De-risks the feedback loop by establishing *when* it is fair to grade a prediction. Without a decay curve, the re-scrape / validation window is guesswork.

**Feasibility:** Medium. Needs publish timestamps + scheduled follow-up scrapes.

**Related:** [Phase 8](Phase_8.md) age-aware validation ([12_AGE_AWARE_VALIDATION.md](current%20md/12_AGE_AWARE_VALIDATION.md)).

---

## Out of Phase 9 scope (removed from this index)

Previously brainstormed under the old T7 independent-modules doc; **not** Phase 9 tasks anymore:

- B1 Content Ideation · B2 Posting-Time Optimizer · B3 Repurposing
- C1 Backtesting · C2 Golden-Set · C3 Model Bake-Off
- D1 Multi-Platform · D2 Browser Composer · D3 Voice Onboarding · D4 Weekly Digest

Revisit later under a different phase if needed.
