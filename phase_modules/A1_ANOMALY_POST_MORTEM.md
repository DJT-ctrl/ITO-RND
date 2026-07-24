# A1 — Anomaly Post-Mortem Agent

**Status:** Implemented (v1 offline batch + Special Cases UI)  
**Owner:** Ademola (from Phase 9 sheet)  
**Phase ID:** **T9.1** (alias A1)  
**Parent:** [Phase 9 index](../Phase_9.md) · [folder README](README.md) · [legacy T7 stub](../T7_INDEPENDENT_MODULES.md)

---

## Run (v1)

```bash
python -m post_mortems.jobs.run_post_mortems --limit 50
python -m post_mortems.jobs.run_post_mortems --dry-run
```

Dashboard: **Check and learn → Special cases** (review library; does not change scores).

Schema: `storage/schema_modules/post_mortems.sql` (applied via `create_schema`).

## One-sentence pitch

Take posts we already **flagged as engagement anomalies**, have an LLM write a short “what went weird and why it matters” note for each, and store those notes as a **case-study library** — without touching the live predict / validate path.

---

## Why is this called “offline”?

“Offline” here does **not** mean “no internet” or “no LLM API.” It means:

| Offline (A1) | Online (live product path) |
|--------------|----------------------------|
| Runs on a schedule or by hand (cron / CLI / batch) | Runs inside a user draft evaluation request |
| Reads rows already in Postgres | Must return a score in seconds |
| Writes to its own table (`post_mortems`) | Touches predictor / feedback injection |
| Failure is “retry later” | Failure is “user sees an error” |
| Cost can be batched and capped | Latency and token cost hit every request |

So: **decoupled from the request path.** Flagging already happened at pipeline finalize time. A1 is a later consumer of those flags. T7’s phrase “zero coupling to the live request path” is the same idea.

Cron vs DB triggers: prefer **cron/CLI**, not triggers. An LLM call on every insert is fragile and expensive; a nightly sweep of `WHERE engagement_anomaly_flag = TRUE AND no post_mortem yet` is safer.

---

## What already exists (before A1)

Anomaly **detection** is already implemented. A1 only **explains and archives**.

| Piece | Where | Role today |
|-------|--------|------------|
| Ratio features | `processors/post_analyser.py` | `comment_ratio = comments/likes`, `share_ratio = shares/likes` (`None` if likes = 0) |
| Flagging | `processors/benchmark.py` → `flag_engagement_anomalies()` | Sets `engagement_anomaly_flag` + `anomaly_reasons[]` |
| Split clean vs flagged | `processors/finalize_records.py` | Flagged posts go to a separate review file; clean set feeds embeddings / main corpus |
| DB columns | `storage/schema.sql` | Same flag + reasons on `posts` |
| Downstream exclusion | e.g. `storage/vector_store.py`, `validation_pipeline/scoring.py` | Often **exclude** flagged posts so bots don’t pollute neighbors / benchmarks |

**Gap:** nothing turns flagged rows into readable lessons. `anomaly_reasons` today is a machine code (`comment_ratio_outlier`), not a narrative.

---

## What counts as an anomaly?

### Intent (from the code’s own docstring)

A high total engagement score is **not** what we flag. Viral organic posts can be high-percentile and still healthy.

What we care about is **implausible mix of engagement types** — classic bot / engagement-pod signal: e.g. comments wildly out of proportion to likes, or shares that don’t look organic relative to the rest of the **same batch**.

### Features used

| Feature | Formula | Notes |
|---------|---------|--------|
| `comment_ratio` | `comments / likes` | Skipped if `likes == 0` (`None` → not scored for that check) |
| `share_ratio` | `shares / likes` | Same |

### Statistical rule (not a simple “top 5%” cut)

This is **not** “percentile &lt; 5 or &gt; 95.” Benchmarks use percentiles for ranking; anomaly flagging uses a **modified z-score** on ratios:

1. Within the current finalize **batch**, take all non-`None` values of `comment_ratio` (then separately `share_ratio`).
2. Compute **median** and **MAD** (median absolute deviation) — robust to outliers (mean/std would be dragged by the bots you’re hunting).
3. Modified z-score:  
   `0.6745 * (value − median) / MAD`
4. Flag if **`|modified_z| > 3.5`**

**Why 3.5?** Conservative cutoff from Iglewicz & Hoaglin outlier guidance — fewer false positives on small batches. Documented in `flag_engagement_anomalies`.

**Guards:**

- Need ≥2 values with that ratio in the batch, or skip the check.
- If MAD = 0 (everyone identical), skip — nothing is an outlier relative to a flat set.
- `None` ratios are skipped, not flagged.

### Reason labels stored today

| `anomaly_reasons` value | Meaning |
|-------------------------|---------|
| `comment_ratio_outlier` | Comment/like mix is an extreme outlier vs batch peers |
| `share_ratio_outlier` | Share/like mix is an extreme outlier vs batch peers |

A post can have one or both. Flag is `TRUE` if the reasons list is non-empty.

### What this is *not*

- Not “underperformed vs prediction” (that’s feedback-loop delta).
- Not “low / high engagement percentile” alone — **that signal is useful**, but it’s a different job (organic smash hits and flops). Parked as a later consideration: [CONSIDERATION_PERCENTILE_EXTREMES.md](CONSIDERATION_PERCENTILE_EXTREMES.md).
- Not a global lifetime threshold (it’s **batch-relative** at finalize time).
- Not a content-quality judgment (text can be fine; the *engagement shape* looks fake or weird).

---

## How a post-mortem helps us learn

Flagging today is a **filter**: keep dirty rows out of the clean corpus. Learning stops there.

A post-mortem turns each flag into a **reusable case study**:

1. **Ground the machine reason** — “`comment_ratio_outlier`” → “Comments ≈ 5× likes vs batch median ~0.1; pattern consistent with pod/bot inflation, not organic discussion.”
2. **Separate signal types** — true viral organic vs fake engagement vs weird niche formats (e.g. invite-only threads) so we don’t teach the Predictor that “high comments always = good.”
3. **Library for later agents** — T7’s intent: curated grounding for Predictor / discoverability / diagnostics (“here are real examples of polluted engagement”).
4. **Human audit trail** — sample post-mortems to tune the 3.5 threshold or add new reason codes later.
5. **Does not change live scores** — learning artifact, not a new calibration knob (unless we later choose to retrieve from `post_mortems` on purpose).

### Suggested post-mortem shape (discussion, not schema yet)

Something short and structured beats a free-form essay:

| Field | Purpose |
|-------|---------|
| `post_id` | Link to `posts` |
| `machine_reasons` | Copy of `anomaly_reasons` at write time |
| `verdict` | e.g. `likely_inorganic` / `plausible_organic_outlier` / `ambiguous` / `data_quality` |
| `summary` | 2–4 sentences: what looked wrong, in plain language |
| `evidence` | Ratios, batch context, percentile if useful — numbers first |
| `lesson_for_models` | One line: what *not* to learn from this post |
| `model` / `generated_at` | Provenance |

Prompt discipline: feed **features + reason codes + text**, ask the model to explain the flag — **not** invent a new statistical rule. If it can’t ground the claim in provided numbers, verdict = `ambiguous`.

---

## Proposed A1 process (still design-only)

```text
posts WHERE engagement_anomaly_flag = TRUE
        AND not yet in post_mortems
              │
              ▼
   Batch job (cron/CLI)
   - Load post text + engagement fields + anomaly_reasons
   - Call Gemini Flash with a fixed post-mortem schema
              │
              ▼
   INSERT post_mortems (...)
   - Never update core validation / predict paths
```

**Acceptance (from Phase 9 / T9.1 sheet, refined):**

- Batch job runnable without touching validation runtime.
- Writes only to `post_mortems` (new table).
- Idempotent: re-run doesn’t duplicate or thrash.
- Optional later: retrieve N post-mortems as grounding — **out of scope for v1**.

---

## Open questions (for us to decide next)

1. **Scope of “anomaly” for A1** — Stay on today’s ratio outliers only for v1? (**Yes recommended.** Percentile extremes → [consideration doc](CONSIDERATION_PERCENTILE_EXTREMES.md); prediction misses stay in the feedback loop.)
2. **Organic viral vs bot** — Should the LLM try to distinguish, or only narrate the statistical flag?
3. **Who consumes post-mortems first?** — Humans (dashboard) vs Predictor grounding vs both.
4. **Batch size / cost** — Cap per night; prioritize newest or most extreme `|z|`.
5. **Re-flag if corpus re-finalized?** — Reasons are batch-relative; post-mortems should snapshot the reasons at generation time.

---

## Relationship to the feedback loop

| Feedback loop ([Phase 8](../Phase_8.md)) | A1 / T9.1 |
|------------------------------------------|-----------|
| About **our predictions** vs later actuals | About **corpus engagement shape** looking fake/weird |
| `prediction_feedback`, calibration, injection | `post_mortems` on flagged `posts` |
| Mostly done engineering; gates for ON | v1 implemented; optional later grounding |

They don’t block each other. A1 does not wait on Phase F GO.

---

## Next chat topics (when you’re ready)

- Harden v1 consumers (dashboard-only vs agent grounding).
- Percentile extremes consideration (separate from ratio anomalies).
- Then **T9.8 / T9.9** — or stay on A1/A2 polish.
