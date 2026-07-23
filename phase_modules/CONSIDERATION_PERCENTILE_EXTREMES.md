# Consideration — Percentile Extreme Case Studies

**Status:** Consideration / later (not A1 v1)  
**ID (provisional):** A1-adjacent · maybe **A5** if we promote it into the module backlog  
**Parent:** [A1 Anomaly Post-Mortem](A1_ANOMALY_POST_MORTEM.md) · [folder README](README.md) · [Phase 9](../Phase_9.md)

---

## The question

A1 intentionally does **not** treat “very high / very low `engagement_percentile`” as an anomaly.

Is that signal still useful? **Yes — for a different job.** This note parks that idea as a **later consideration phase**, so we don’t overload A1’s bot/ratio meaning.

---

## Two different “outliers”

| | **A1 — Ratio anomaly (now)** | **This consideration — Percentile extreme (later)** |
|--|------------------------------|-----------------------------------------------------|
| **Question** | Does engagement *mix* look fake or weird? | Did this post *crush* or *bomb* vs peers? |
| **Signal** | `comment_ratio` / `share_ratio` modified z &gt; 3.5 | e.g. percentile ≤5 or ≥95 (thresholds TBD) |
| **Typical story** | Pod/bot pollution, weird reaction shape | Organic viral hit, or genuine flop |
| **Corpus action today** | Often **excluded** from clean set / neighbors | Usually **kept** — this *is* the ranking signal |
| **Risk if mixed into A1** | We teach “viral = anomalous = distrust” | Pollutes bot-detection lessons with real wins/losses |

Mixing them in one `engagement_anomaly_flag` would blur “don’t trust this engagement” with “study this performance.” Keep the flags and libraries separate.

---

## Why percentile extremes *are* helpful

1. **Positive case studies** — Top-decile / top-5% posts are exactly what ideation, voice, and Predictor grounding want (“what worked”).
2. **Negative case studies** — Bottom extremes teach flop patterns (weak hook, wrong length, dead topic) without needing a failed *prediction*.
3. **Complements the feedback loop** — Feedback is “our score vs later actual.” Percentile extremes are “this post’s place in the corpus,” even with no prediction row.
4. **Complements A1** — After A1 filters inorganic noise, extreme *clean* percentiles are safer to narrate as real performance.

So: not “instead of A1” — **after** (or beside) A1, with a clear label like `performance_extreme` not `engagement_anomaly`.

---

## Sketch of a later phase (design only)

**Working name:** Percentile Extreme Case Studies (or **A5** if promoted).

**Inputs (already in DB):**

- `engagement_percentile` (and optionally `audience_adjusted_percentile`)
- Post text + Stage-1/2 features
- Prefer `engagement_anomaly_flag = FALSE` so bot-shaped rows don’t become “viral lessons”

**Selection rule (TBD — examples only):**

| Band | Example cut | Intent |
|------|-------------|--------|
| Smash hit | percentile ≥ 95 (or ≥ 90) | What to emulate |
| Soft underperformer | percentile ≤ 10 | Mild miss patterns |
| Hard flop | percentile ≤ 5 | Strong negative examples |

Audience-adjusted percentile may be fairer when follower counts vary — decide when we promote this.

**Output:** Same *shape* as A1 post-mortems is fine (summary, evidence, lesson), but:

- Separate table **or** shared `case_studies` with `kind = ratio_anomaly | percentile_extreme`
- Verdicts like `organic_hit` / `organic_flop` / `context_dependent` — not `likely_inorganic`

**Process:** Still offline batch (cron/CLI). Still no live-path coupling.

---

## Why not do this inside A1 v1

1. **Detection already exists for ratios; percentile bands need a new product decision** (5/95 vs 10/90, raw vs audience-adjusted, min sample size).
2. **Exclusion semantics differ** — ratio flags are often *removed* from learning corpora; percentile extremes should usually *stay*.
3. **Prompt and lessons differ** — A1: “why distrust this engagement.” Extremes: “why this content worked/failed.”
4. **Keeps A1 shippable** — consume existing flags first; add a second lane when we want win/loss libraries.

---

## Dependencies / order

```text
A1 (ratio post-mortems)
  → optional: human sample of A1 quality
  → this phase (percentile extremes on clean posts)
  → later: retrieve either library into Predictor / ideation / digest
```

Also plays nicely with:

- **B1 Ideation** — smash-hit case studies as inspiration
- **C1 Backtesting** — flops/hits as hard examples (separate from prediction error)
- **D4 Weekly digest** — “top / bottom of your niche this week”

---

## Open questions (when we promote this)

1. Cuts: 5/95, 10/90, or z-score on `log1p(engagement)` instead of percentile?
2. Raw vs `audience_adjusted_percentile` as primary band?
3. Same `post_mortems` table with a `kind` column, or separate `performance_case_studies`?
4. Exclude A1-flagged posts always, or allow dual tags with clear precedence?
5. Cap volume (e.g. only newest N per band) so LLM cost stays bounded?

---

## Decision for now

| Decision | Choice |
|----------|--------|
| Is “very high/low percentile” helpful? | **Yes**, as performance case studies |
| Put it in A1 v1? | **No** |
| Track it where? | This consideration doc; promote to a numbered module when we leave A1 |

No code until A1 scope is settled and we explicitly promote this phase.
