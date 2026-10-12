# Later

Open follow-ups. Add a line when something is built but not proven, or when it is deliberately left for a later pass. Remove a line when it is done.

## Stored-post feedback

Code is on `feat/stored-post-feedback` ([pull request #15](https://github.com/DJT-ctrl/ITO-RND/pull/15)). Package notes: [post_feedback/README.md](post_feedback/README.md).

**Not tested end to end.** `tests/test_post_feedback.py` passed with no database and no Gemini. Nobody has yet:

- [ ] Run `python -m post_feedback.jobs.run_post_feedback --dry-run --limit 50` against a database that already has labelled posts
- [ ] Run a small real batch (`--limit` well under 50) and read the stored summary, edits, and neighbor notes
- [ ] Approve and reject one row from `render_post_feedback_section`
- [ ] Confirm a second run skips posts that already have a row
- [ ] Confirm posts with `engagement_anomaly_flag` are not written

Do not treat the write-ups as trusted coaching until those checks have been done.

### Left out of this version on purpose

- [ ] Summarise approved notes into a winning-formula view (by hook, topic, and percentile band). Corpus stats already live in `processors/pattern_analysis.py`.
- [ ] Inject approved notes into predict-time prompts. That waits on the same lift gate as the feedback loop.
- [ ] Mount `render_post_feedback_section` on the Special Cases page. The helper exists; no page imports it yet.
- [ ] Add a nightly cap. Operators pass `--limit` by hand for now.
