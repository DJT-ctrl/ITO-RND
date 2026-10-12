# Stored-post feedback

**Not tested end to end.** Unit tests in `tests/test_post_feedback.py` passed without Postgres or Gemini. The batch has not been run against a real database, a real model call, or the review screen. Track that under [LATER.md](../LATER.md).

Offline write-ups for posts that are already in Postgres. Each note says what worked, what to change, and how the post compares with similar posts. It does not change live prediction scores.

This is not the draft evaluation path. A draft you send through evaluation already gets SEO, clarity, and tone feedback (`agents/diagnostics.py`) plus predictor reasoning (`agents/predictor.py`). Those agents stay as they are.

This package is for **corpus posts**: rows that were scraped, stored, and categorised. Gemini tags and Hugging Face categories stay a cheap labelling pass. This job runs later, reads those labels, and writes a reviewable note.

## Where it sits

```text
scrape → store → categorise (Gemini tags, Hugging Face scores)
                      ↓
              post_feedback batch   (this package)
                      ↓
              post_feedback table → approve or reject
```

| Already in the repo | What it explains | This package |
| --- | --- | --- |
| `agents/diagnostics.py` | A draft you are evaluating | Leaves that path alone |
| `feedback/` | Why a prediction missed the later actual percentile | Does not write those lessons |
| `post_mortems/` | Posts whose like/comment/share mix looks suspicious | Does not touch flagged posts |
| `processors/pattern_analysis.py` | Corpus-wide averages and correlations | Does not replace those stats |

Nothing here is injected into the predictor. Live learning stays behind the existing go/no-go gate.

## What a write-up contains

Stored on `post_feedback` (see `storage/schema_modules/post_feedback.sql`):

| Field | Meaning |
| --- | --- |
| `summary` | Short read of the post against its percentile and labels |
| `what_worked` | Bullets tied to a supplied label, metric, or neighbor |
| `what_to_change` | Concrete edits grounded in the same evidence |
| `neighbor_notes` | Up to 5 similar posts. Percentile gap versus this post, plus hook, length, CTA, and topic differences when those fields exist |
| `evidence` | The exact metrics, labels, and neighbor ids the model was given |
| `review_status` | `pending`, then `approved` or `rejected` |

Neighbor notes are calculated in `post_feedback/prompt.py` from the post's existing embedding. `find_similar` is called with that vector. The source post is dropped. There is no second embedding call.

The model is told to cite only those facts. Post text is wrapped as untrusted data (`agents/prompt_safety.py`). If the write-up does not mention a supplied number or label, the row is not stored.

New rows start as `pending`. A re-run does not overwrite them. `INSERT ... ON CONFLICT (post_id) DO NOTHING` keeps one row per post, including rows you have rejected.

## Which posts are eligible

All of the following:

- `engagement_anomaly_flag` is false. Flagged posts stay on the anomaly post-mortem job.
- The post does not already have a `post_feedback` row.
- There is real label evidence: a Gemini hook, tone, topic, writing style, or CTA, or a Hugging Face label section (`labeler = huggingface`).

Posts with neither label section are left out. A write-up from raw text alone would invent quality judgements the categorisers have not made.

The batch is capped. Pass `--limit`. It does not walk the whole history in one run.

## Run

Requires `DATABASE_URL`. The first run applies `storage/schema_modules/post_feedback.sql` through `create_schema`.

```bash
# Count eligible posts. No model call, no writes.
python -m post_feedback.jobs.run_post_feedback --dry-run --limit 50

# Write up to 50 notes.
python -m post_feedback.jobs.run_post_feedback --limit 50
```

Exit code `0` means no post failed. Exit code `2` means at least one post failed and the rest continued. Exit code `1` means configuration is missing (`DATABASE_URL`).

Dry-run reports eligible posts as `skipped`. A write run reports `generated` for new rows and `skipped` when a post already had a row.

## Review

`post_feedback/ui.py` exposes `render_post_feedback_section`, the same kind of Streamlit helper as `post_mortems/ui.py`. It is not mounted on a page in this repo. Place it on the Special Cases page when that page is wired.

The helper lists pending rows first. Approve and reject set `reviewed_by` to `dashboard` and do not change percentiles.

From code:

```python
from post_feedback.store import set_review_status

set_review_status(conn, post_id, "approved", reviewed_by="your-name")
```

`pending` is only the initial status. Review updates are `approved` or `rejected`.

## Tests

```bash
python -m pytest tests/test_post_feedback.py -q
```

The tests do not need Postgres or Gemini. They check that the prompt only carries supplied evidence, that generation works under `TestModel`, that anomaly and unlabelled posts are excluded, and that a second insert for the same post does nothing.

Those checks are the only verification so far. Still to do, and listed in [LATER.md](../LATER.md):

- `--dry-run` against a database that already has labelled posts
- A small `--limit` run that actually calls Gemini and writes rows
- Approve or reject one row in `render_post_feedback_section`

## Not in this version

- No roll-up that turns approved notes into a winning-formula model. Corpus pattern stats already live in `processors/pattern_analysis.py`.
- No injection of these notes into predict-time prompts.
- No nightly cap beyond the `--limit` you pass.
