# A2 — Trend Radar & Topic-Drift Monitor

**Status:** Implemented (v1 offline weekly batch + Special Cases UI)  
**Owner:** Ademola (from Phase 9 sheet)  
**Parent:** [T7 Independent Modules](../T7_INDEPENDENT_MODULES.md) · [Phase 9 index](../Phase_9.md) · [folder README](README.md)

**Related consideration:** External / popular-content trend APIs → [CONSIDERATION_EXTERNAL_TREND_TRACKER.md](CONSIDERATION_EXTERNAL_TREND_TRACKER.md)

---

## Run (v1)

```bash
python -m trend_radar.jobs.run_trend_radar --week 2026-07-20
python -m trend_radar.jobs.run_trend_radar --dry-run --skip-llm-labels
```

Uses `posts.inserted_at` for the week window (no `posted_at` on `posts`).  
Excludes `engagement_anomaly_flag = TRUE`.  
Dashboard: **Check and learn → Special cases** (trends section).

Schema: `storage/schema_modules/trends.sql`.

## One-sentence pitch

On a schedule, **cluster your own LinkedIn (corpus) embeddings**, measure which topics are **growing or shrinking week over week**, and write those signals into a `trends` table for ideation, SEO, and digests — without touching the live predict path.

---

## Why this is “offline”

Same meaning as A1: **not on the user request path.**

| Offline (A2) | Online (live path) |
|--------------|--------------------|
| Weekly (or nightly) batch over stored embeddings | Draft evaluation must stay fast |
| Writes `trends` | May *read* trends later as context |
| Clustering can be slow / CPU-heavy | Must not block Predictor / SEO request |

T7: “Runs on a schedule independent of any user session.”

---

## What problem it solves

Today’s discoverability stack already has:

| Layer | What it is | Limit |
|-------|------------|--------|
| **Tier 1** | Neighbors + corpus benchmarks (`agents/discoverability*`) | Snapshot of “what’s in our DB,” not *motion* over time |
| **Tier 2** | Google Trends via `processors/trend_signals/` | **Web search interest**, explicitly *not* LinkedIn feed performance |

A2 fills the gap: **LinkedIn-specific topic motion inside *your* scraped corpus** — “what’s accelerating in the data we actually score against,” not “what people Google.”

That’s why T7 calls it the best primary signal for grounded LinkedIn discoverability, with external APIs as a complement (see consideration doc).

---

## What “topic drift” means here

Not “the user’s voice drifted.” It means:

1. Embeddings live in ~3072-d space (Gemini embed + pgvector).
2. A clustering pass groups posts into **topic clusters**.
3. Each week you compare cluster **size / share / engagement** to last week.
4. Clusters that **grow fast** = rising; shrink = cooling; new clusters = emerging.

**Drift** = the map of topics changing over fixed increments (T7: weekly).

---

## What already exists (inputs)

| Asset | Where | Role for A2 |
|-------|--------|-------------|
| Post embeddings | `posts` + pgvector / `data/embeddings/` | Vectors to cluster |
| Post metadata | `posted_at`, topic tags, engagement | Weight clusters; time windows |
| Optional Gemini `topic` tags | Stage-2 features | Labels / sanity checks — not a substitute for embedding clusters |
| Google Trends (Tier 2) | `processors/trend_signals/google_trends.py` | **Different product** — keep separate; see consideration |

A2 does **not** require the feedback loop to be GO. It needs a reasonably large, dated embedding corpus.

---

## Proposed outputs (design only)

A persistent `trends` table (name TBD), e.g. rows per `(week_start, cluster_id)`:

| Field (sketch) | Purpose |
|----------------|---------|
| `cluster_id` | Stable-ish id for the topic blob |
| `label` | Human/LLM short name (“AI regulation”, “layoff stories”…) |
| `post_count` / `share_of_corpus` | Size this period |
| `growth_rate` / `acceleration` | WoW or vs trailing baseline |
| `mean_engagement` / percentile band | Rising *and* performing? |
| `example_post_ids` | Grounding for agents |
| `computed_at` | Provenance |

Downstream consumers (later): **B1 ideation**, discoverability/SEO, **D4 weekly digest**.

---

## Hard parts (why “medium” effort despite “high feasibility”)

| Challenge | Why it matters |
|-----------|----------------|
| **Cluster stability** | k-means IDs reshuffle; week-over-week growth needs matching (centroids, Hungarian assign, or incremental methods) |
| **Label quality** | Raw cluster ids are useless to humans/agents — need LLM or keyword labels |
| **Corpus bias** | Trends reflect *what you scraped*, not all of LinkedIn |
| **Anomalies** | Prefer excluding `engagement_anomaly_flag` posts so bots don’t invent fake topics (ties to A1) |
| **Min N** | Tiny clusters are noise; need floors on size before “rising” |

v1 can be humble: fixed weekly job, mean/HDBSCAN or k-means, growth table, LLM labels offline — no live wiring.

---

## How A2 relates to external “popular content” APIs

| | **A2 (this doc)** | **External tracker (consideration)** |
|--|-------------------|--------------------------------------|
| Source | Your Postgres embeddings | Third-party / platform “what’s hot” APIs |
| Strength | LinkedIn-shaped, aligned to *your* scoring world | Broader, fresher, outside scrape lag |
| Weakness | Blind to topics you never scraped | Not LinkedIn-native; ToS/cost/noise |
| Role | **Primary** corpus radar | **Secondary** freshness / cross-check |

Best product story later: **intersect** — “rising in our corpus **and** hot externally” vs “only Google-hot” vs “only our niche.”

Details, API options, and how this differs from today’s Google Trends Tier 2:  
→ [CONSIDERATION_EXTERNAL_TREND_TRACKER.md](CONSIDERATION_EXTERNAL_TREND_TRACKER.md)

---

## Acceptance (from Phase 9, refined)

- Scheduled clustering writes labels + growth indicators to `trends`.
- Does not modify validation / predict runtime paths.
- Exposes a clear read path for later agents (SQL/API), even if nothing consumes it in v1.
- Documented caveat: trends = corpus-relative, not global LinkedIn truth.

---

## Open questions

1. Cadence: weekly only, or weekly + daily lightweight refresh?
2. Algorithm: k-means vs HDBSCAN vs “centroid attach to last week”?
3. Growth metric: post count, share of corpus, or engagement-weighted?
4. Exclude A1-flagged posts always?
5. When do we wire into SEO/ideation — v1 table only, or v1 + prompt injection?

---

## Suggested order vs other modules

```text
A1 (clean ratio anomalies)     optional hygiene before clustering
  → A2 corpus Trend Radar      this doc
  → External popular-content tracker   consideration (can parallel once A2 schema exists)
  → B1 / D4 consume trends
```

A2 can start without A1, but excluding flagged posts is cleaner once A1’s flags are trusted in DB.
