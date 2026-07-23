# Consideration — External Popular-Content Trend Tracker

**Status:** Consideration / later (complements A2; not A2 v1)  
**ID (provisional):** A2-adjacent · maybe **A6** if promoted  
**Parent:** [A2 Trend Radar](A2_TREND_RADAR.md) · [folder README](README.md) · [Phase 9](../Phase_9.md)

---

## The idea

A2 watches **topic drift inside our scraped corpus**.  

Separately, a **trend tracker wired to an external API** that surfaces **popular / trending content** (or search/social heat) would add a second radar: what’s hot *outside* our DB — news cycles, platform trends, niche keywords — so ideation and SEO aren’t limited to whatever we happened to scrape last month.

That combination works well: **corpus truth + world freshness.**

---

## Why this is *not* the same as A2

| | **A2 — Corpus Topic-Drift** | **This — External popular-content tracker** |
|--|-----------------------------|-----------------------------------------------|
| Data | Our embeddings / posts | API: trending posts, topics, headlines, search |
| Question | “What’s accelerating *in our niche corpus*?” | “What’s popular *out there* right now?” |
| Lag | Depends on scrape cadence | Often nearer real-time |
| Bias | Scrape filters, creator set | Platform ranking, geography, API product bias |
| Cost | Mostly compute | API quotas, ToS, possible paid plans |

Don’t merge into one `trends` row type without a `source` field. Agents should know which lens they’re reading.

---

## What we already have (don’t reinvent blindly)

**Google Trends (Tier 2)** already exists for the SEO path:

- `processors/trend_signals/google_trends.py` + `keywords.py`
- Wired via `agents/discoverability_context.py` when `use_google_trends` is on
- Explicit disclaimer: *web-wide search interest, not LinkedIn feed performance*

So “call an external trend API” is partially done — but only as:

- **On-demand**, per draft keywords  
- **Search interest**, not “popular posts / viral LinkedIn content”  
- **Not** a scheduled library written into a `trends`-like table for ideation/digest

This consideration is about a **stronger / broader external lane**, possibly including *popular content*, not only pytrends search curves.

---

## What “popular content” APIs might mean (options)

Pick later; list is for discussion:

| Direction | Examples of shape | Fit |
|-----------|-------------------|-----|
| **Search interest** | Google Trends (already), similar keyword APIs | Timeliness of *terms*; weak on “what posts are winning” |
| **News / web hot** | News APIs, HN/Reddit-style firehoses, RSS topic feeds | Good for B2B narrative timing; not LinkedIn-native |
| **Platform-native social** | Wherever ToS-allowed: LinkedIn-adjacent intel, X trends, etc. | Highest relevance; highest legal/scrape risk |
| **Creator/niche lists** | Curated “top posts this week” from partners or internal Apify *trend scrapes* | Closest to product; still “external” to the main corpus job |

Honest constraint: **true LinkedIn “trending” APIs are limited**; many products fake this with scrapers or proxies. Any platform scrape needs a ToS/compliance check before we treat it as a phase.

---

## How it would work with A2 (the useful combo)

```text
                    ┌─────────────────────┐
   Corpus embeds →  │  A2 trends table    │  “rising in OUR data”
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  Join / compare      │  rising_both / corpus_only / external_only
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
   External APIs →  │  external_trends    │  “hot out THERE”
                    └─────────────────────┘
                              │
              B1 ideation · SEO · D4 digest
```

**Example agent framing:**

- *Rising both* → strong bet  
- *External only* → early / outside our scrape (opportunity or irrelevant)  
- *Corpus only* → niche alpha Google won’t show  

That’s stronger than either radar alone.

---

## Proposed later shape (design only)

| Piece | Notes |
|-------|--------|
| Scheduled job | Nightly/weekly fetch → normalize → store |
| Table | e.g. `external_trends` or `trends` with `source = corpus \| google_trends \| news \| …` |
| Fields | topic/keyword, window, score/rank, url/examples, fetched_at, raw payload ref |
| Consumer | Same read path as A2 for B1/D4; SEO can prefer corpus, use external as hint |
| Fail-open | If API dies, corpus A2 still works (mirrors today’s Trends degrade) |

---

## Relation to Google Trends Tier 2 today

| Today (Tier 2) | This consideration |
|----------------|--------------------|
| Live path optional context | Offline scheduled library (+ optional live) |
| Keywords from *this draft* | Catalog of what’s hot (then match to draft/niche) |
| Search interest only | May add popular *content* / headlines / social |
| Cached per keyword file | First-class DB rows for digests & ideation |

Promotion path could be: **extend** `trend_signals` into a scheduled writer, **or** add new sources beside Google — without replacing A2.

---

## Why not fold into A2 v1

1. A2’s hard problem is **clustering stability** — don’t add API ToS, quotas, and schema fights in the same PR.
2. External feeds need product/legal picks (which API is allowed).
3. We already have a thin Google Trends path; prove corpus radar first, then invest in a richer external library.
4. Clear `source` semantics are easier once `trends` (corpus) exists.

---

## Risks

- **ToS / scraping** — especially anything that pretends to be “LinkedIn trending”
- **Noise** — global viral ≠ your ICP
- **Cost & rate limits** — batch + cache mandatory
- **Stale trust** — agents must see `fetched_at` and source disclaimer (same spirit as current Trends disclaimer)

---

## Open questions (when we promote)

1. Is v1 of this just **scheduled Google Trends for our top corpus topics** (cheap extension), or a true **popular-content** source?
2. Which verticals / geos matter?
3. Shared `trends` table with `source`, or separate `external_trends`?
4. Who consumes first — D4 digest, B1 ideation, or SEO only?
5. Compliance owner for any platform-native scrape?

---

## Decision for now

| Decision | Choice |
|----------|--------|
| Is an external popular-content / API tracker a good idea? | **Yes**, as a second radar |
| Part of A2 v1? | **No** — A2 = corpus drift first |
| Track where? | This consideration; link from A2 |
| Reuse Google Trends code? | Likely as *one* source later, not the whole story |

No code until A2 scope is settled and we pick an allowed external source.
