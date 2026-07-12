# 06 — Open Questions

**Status:** For team review before build  
**Next step:** Daniel shares this folder with the team; align on data model + Phase A scope

---

## Data model

- [ ] **Separate `prediction_feedback` table vs JSONB column on `predictions`?**  
  Recommendation: separate table (versioning, regeneration). Confirm with team.

- [ ] **`prediction_deltas` as a named view** — useful for analytics exports, or is querying `predictions WHERE status = 'validated'` enough?

- [ ] **Backfill validated posts into `posts` corpus?**  
  Ground-truth percentiles from live validation could improve neighbor retrieval. Trade-off: corpus contamination if rescrape window is wrong.

---

## Feedback generation

- [ ] **Who generates feedback — template rules, LLM, or hybrid?**  
  Proposal: template for small deltas; LLM with strict schema for large misses.

- [ ] **Human review queue?**  
  Useful for high-magnitude errors during testing phase. Optional for v1.

- [ ] **Feedback schema v1 fields** — finalise required vs optional fields before migration.

---

## Clustering

- [ ] **Initial cluster definition** — metadata rules (length, format) vs embedding k-means? (LLM routing ruled out — see doc 05)

- [ ] **Minimum cluster size before cluster-scoped retrieval** — fallback to global if cluster has < N validated rows?

- [ ] **Cluster labelling** — optional LLM pass to generate human-readable cluster names for the dashboard (does not assign routing)

---

## Validation window

- [ ] **Is 48h the right default for all post types?**  
  T7 A4 (engagement decay capture) would inform this. Build feedback system with 48h assumption or block on decay data?

- [ ] **Multi-window snapshots** — store 48h actual as primary grade, but also 7d for long-tail posts?

---

## Integration

- [ ] **Sync vs async feedback generation** — inline in validation worker, or separate job queue?

- [ ] **A/B testing framework** — how do we compare predictor with vs without feedback injection? Re-use evaluation cycle harness?

- [ ] **Dashboard surface** — new page for feedback review, or extend Validation Queue / Accuracy History?

---

## Scope for first PR

Suggested minimal slice to agree on:

1. Global `mean_delta` calibration offset in `processors/benchmark.py` (or `feedback/calibration.py`) with **`N_min` gate** + settings flag
2. Log calibrated vs raw percentile in telemetry for comparison
3. Unit tests locking delta sign: `calibrated = clamp(raw + mean_delta, 0, 100)`
4. (Optional same PR or immediate follow-up) `prediction_feedback` table migration + template batch job for newly validated rows (no LLM yet)

Everything else (deterministic routing, LLM feedback, per-cluster stats, context caching) ships incrementally.

See also [07 — Peer Review](07_PEER_REVIEW.md) and [08 — Build Practices](08_BUILD_PRACTICES.md).

---

## Resolved decisions

- **LLM routing agent** — ruled out. Routing is required at scale but done deterministically (embedding → centroid).
- **Structured data transformers** — ruled out. Retrieval + calibration is the right fit; revisit only if accuracy plateaus.
- **Context caching** — useful at scale for stable cluster/global prompt prefixes (cost + speed), not for learning. See doc 05.
- **Delta sign** — `prediction_delta = actual − predicted`; calibration adds `mean_delta` (see doc 05).
- **Calibration cold start** — do not apply offsets until `N_min`; fail open (predict without learning).
- **Feedback generation** — async after `mark_validated`; never inside rescrape failure path.
- **Code layout** — keep feedback out of a growing `worker.py`; follow [08 — Build Practices](08_BUILD_PRACTICES.md).

---

## Ideas welcome

Daniel flagged this as a big step and invited team input. Add comments or PRs to this folder, or discuss in standup before implementation starts.
