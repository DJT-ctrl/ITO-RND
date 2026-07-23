# Phase 9 — Independent Modules Index

**Status:** Planning  
**Source:** Same backlog as [`T7_INDEPENDENT_MODULES.md`](T7_INDEPENDENT_MODULES.md)  
**Deep-dive folder:** [`phase_modules/`](phase_modules/README.md)

Spreadsheet-style rows lived here earlier; this file is now the **index**. Each module we discuss gets a focused note under `phase_modules/`.

---

## Modules

| ID | Module | Focused doc | Status |
|----|--------|-------------|--------|
| **A1** | Anomaly Post-Mortem Agent | [phase_modules/A1_ANOMALY_POST_MORTEM.md](phase_modules/A1_ANOMALY_POST_MORTEM.md) | Implemented (v1) |
| *(later)* | Percentile extreme case studies | [phase_modules/CONSIDERATION_PERCENTILE_EXTREMES.md](phase_modules/CONSIDERATION_PERCENTILE_EXTREMES.md) | Consideration (after A1) |
| **A2** | Trend Radar & Topic-Drift Monitor | [phase_modules/A2_TREND_RADAR.md](phase_modules/A2_TREND_RADAR.md) | Discussing |
| *(later)* | External popular-content trend tracker | [phase_modules/CONSIDERATION_EXTERNAL_TREND_TRACKER.md](phase_modules/CONSIDERATION_EXTERNAL_TREND_TRACKER.md) | Consideration (after / beside A2) |
| B2 | Posting-Time Optimizer Engine | — | Planning |
| C1 | Historical Backtesting & Calibration Harness | — | Planning |
| D3 | Voice-Fingerprint Onboarding Pipeline | — | Planning |
| D1 | Multi-Platform Expansion Infrastructure | — | Planning |
| C2 | Golden-Set Regression Test Suite | — | Planning |
| A3 | Comment & Reaction Mining Engine | — | Planning |
| A4 | Engagement-Decay Tracking Service | — | Planning |
| B1 | Automated Content Ideation Agent | — | Planning |
| D2 | In-Context Browser Composer Extension | — | Planning |
| B3 | Long-Form Content Repurposing Pipeline | — | Planning |
| C3 | Model Bake-Off Diagnostic Matrix | — | Planning |
| D4 | Weekly Performance & Trend Digest | — | Planning |

Recommended start order (from T7): **A1 → B2 → C1 → D3**, then the rest.

---

## A1 snapshot (see focused doc for full discussion)

- **What:** Offline batch job over `engagement_anomaly_flag = TRUE` → LLM post-mortem → `post_mortems` table.
- **Why “offline”:** Not on the live predict path; cron/CLI consumer of flags already set at finalize.
- **What is an anomaly:** Batch-relative **modified z-score &gt; 3.5** on `comment_ratio` or `share_ratio` (not “top/bottom percentile” alone). See [A1 doc](phase_modules/A1_ANOMALY_POST_MORTEM.md).
- **Percentile extremes (hits/flops):** Useful later as a separate case-study lane — not mixed into A1’s bot/ratio flag. See [consideration](phase_modules/CONSIDERATION_PERCENTILE_EXTREMES.md).

---

## A2 snapshot (see focused doc for full discussion)

- **What:** Offline clustering of corpus embeddings → week-over-week growth → `trends` table (LinkedIn-shaped, scrape-relative).
- **Why it matters:** Complements neighbors/benchmarks; stronger LinkedIn signal than Google-only trends.
- **External popular-content APIs:** Great as a **second radar** (world freshness). Keep separate from A2 v1; see [consideration](phase_modules/CONSIDERATION_EXTERNAL_TREND_TRACKER.md). Note: on-demand Google Trends Tier 2 already exists for SEO — this consideration is a broader scheduled / popular-content lane.
