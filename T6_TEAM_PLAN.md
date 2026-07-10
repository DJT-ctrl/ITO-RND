# T6 Team Additions Plan
**Date:** 2026-07-08
**Status:** Planning
**Owner:** Erdal / Team

---

## Point 1 — Tracking Poster History & Reach Bias

**Problem:** The Predictor Agent compares a draft against 10 nearest historical posts using absolute engagement figures. A creator with 1M followers gets thousands of views regardless of content quality. This skews accuracy and makes the engagement benchmark misleading.

**Solution:** Add a secondary profile scraper to pull follower counts per author so engagement can be normalized by audience size.

**What this affects:**
- Scraping footprint doubles — a necessary cost to fix the underlying bias
- Engagement benchmarks must be recalculated against follower-normalized rates
- The Predictor's neighbor context prompt must surface normalized figures, not raw totals

**Key tasks for T6 tracker:**
- Run profile scraper for all existing `author_public_id` values in the posts table (backfill pass)
- Add `follower_count` to the database schema
- Populate the `engagement_rate` column (already reserved in the schema but currently unpopulated)
- Update benchmark scoring in `processors/benchmark.py` to use normalized engagement
- Update the Predictor Agent's neighbor context to include normalized rate alongside raw counts

---

## Point 2 — Transitioning to Grounded SEO Agents (Phase 3 / T3.3)

**Problem:** The current SEO Diagnostic Worker in `agents/diagnostics.py` relies entirely on Gemini's static training knowledge. The team flagged this in the architecture diagram: *"How does it know what SEO works? Hook up to SEO tool?"* The agent cannot evaluate real-time discoverability or current search trends.

**Solution:** Upgrade the SEO Diagnostic Worker from a pure prompt into a live agent by enabling Gemini Google Search grounding or connecting to a live Google Search / Analytics node.

**What this affects:**
- The SEO worker becomes the first genuinely tool-using agent in the pipeline (text-in/text-out → text-in/tool-call/text-out)
- Adds latency and cost per evaluation cycle (needs monitoring)
- Makes test mocking more complex — the grounded path must degrade gracefully if the search call fails
- Important distinction: LinkedIn discoverability is driven by LinkedIn's feed algorithm and hashtag/keyword signals, not Google rank. Grounding provides real-time topic/trend freshness — clarify with the team what "SEO" means specifically for LinkedIn posts vs. Google search

**Key tasks for T6 tracker:**
- Enable Gemini Google Search grounding on the SEO diagnostic agent
- Add graceful degradation: if grounding fails, fall back to static knowledge and log the failure
- Define what "SEO score" means for LinkedIn specifically (hashtag relevance, topic signals, trending keywords)
- Add response caching so the same topic doesn't fire a live search repeatedly

---

## Point 3 — New T6 Tracking Section in Project Management Dashboard

**Problem:** The current PM tracker (`intotheopen_ Project Management Dashboard - intotheopen_ Erdal.csv`) has no phase covering scraper updates, agent tool integrations, or the data model adjustments required by Points 1 and 2.

**Solution:** Append a T6 phase/section to the tracker to explicitly map out these additions.

**Suggested T6 line items:**
| Phase | Task | Description |
|-------|------|-------------|
| T6 | T6.1 | Profile scraper integration — backfill follower counts for all existing authors | Done — `processors/run_enriched_backfill.py` + `processors/run_profile_enrichment.py` |
| T6 | T6.2 | DB schema migration — add `follower_count` column, populate `engagement_rate` | Done — `storage/schema.sql` + enriched pipeline path |
| T6 | T6.3 | Benchmark normalization — update scoring pipeline to use reach-adjusted engagement | Done — `processors/benchmark.py::add_audience_adjusted_benchmark` |
| T6 | T6.4 | Grounded SEO agent — enable live search grounding on the SEO Diagnostic Worker | In progress — Tier 1 corpus + Tier 2 Google Trends landed |
| T6 | T6.5 | Predictor prompt update — surface normalized engagement in neighbor context | Done — deterministic `compute_neighbor_prediction` drives score |
| T6 | T6.6 | Profiles scrape cache — prevent re-scraping the same author across runs | Done — `storage/profile_store.py` + `profiles` table |
