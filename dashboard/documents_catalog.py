"""Hardcoded Documents catalog for the dashboard Documents page.

Paste / replace body_markdown entries here when you submit planning notes.
No filesystem browser — intentional.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardDocument:
    id: str
    title: str
    plain_summary: str
    body_markdown: str
    tags: tuple[str, ...] = ()


DOCUMENTS: tuple[DashboardDocument, ...] = (
    DashboardDocument(
        id="welcome",
        title="How to use Documents",
        plain_summary="What this page is for, and how new notes get added.",
        tags=("meta",),
        body_markdown="""
## Documents

This area holds **planning notes and project docs** in plain English so a new
joiner can read them without digging through the repo.

### Adding content

1. Paste the markdown (or notes) into chat when you are ready.
2. We hardcode it into `dashboard/documents_catalog.py` as a new entry below.
3. It then appears in the list on the left of this page.

Nothing is uploaded from the UI on purpose — the catalog stays reviewable in git.
""",
    ),
    DashboardDocument(
        id="placeholder-planning",
        title="Planning notes (paste later)",
        plain_summary="Reserved slot for your active planning notes.",
        tags=("planning", "placeholder"),
        body_markdown="""
## Planning notes

*Placeholder — content will be hardcoded when you submit it.*

Suggested topics to drop here later:
- Current go / no-go decision
- How you operate the feedback loop day to day
- Open questions and next experiments
""",
    ),
    DashboardDocument(
        id="placeholder-onboarding",
        title="Onboarding cheat sheet (paste later)",
        plain_summary="Reserved slot for a “start here” sheet for new people.",
        tags=("onboarding", "placeholder"),
        body_markdown="""
## Onboarding cheat sheet

*Placeholder — content will be hardcoded when you submit it.*

Good material for this slot:
- What the product is trying to do in one paragraph
- Corpus path vs validation path (which pages to open first)
- What *not* to turn on in production (calibration / injection)
""",
    ),
    DashboardDocument(
        id="phases-a-j",
        title="Phases A–J (plain English)",
        plain_summary="Built-in summary of every feedback-loop phase and status.",
        tags=("feedback", "phases"),
        body_markdown="""
## Phases A–J

These letters show up as **color pills** across the dashboard. Same colors everywhere.
Each row below has a short “what”, extra detail, and a concrete example.

| Phase | What it does | Detail + example | Status |
|-------|--------------|------------------|--------|
| **0** Foundation | Grade predictions once real engagement exists | Stores predicted vs real engagement so later phases can learn. *Ex:* predicted 72nd → real 45th → we record the miss. | Done |
| **A** Calibration | Nudge predicted percentile using past errors | Numeric offset from recent mistakes (not a full model retrain). Prod OFF until F is GO. *Ex:* often over by ~8 on short text → subtract ~8 next time. | Done, prod OFF |
| **B** Lessons | After grading, store a short template lesson | Raw material for buckets / injection / smarter lessons. Usually ON even when A/D stay OFF. *Ex:* “Carousel for founders: hooks buried below the fold.” | Done |
| **C** Buckets | Route posts into length × format × audience groups | Keeps lessons from long video out of short-text advice. *Ex:* `medium × text × marketers` vs `short × carousel × founders`. | Done |
| **D** Injection | Put recent same-bucket lessons into the predictor prompt | Model sees past lessons, not only a number nudge. Prod OFF until F. *Ex:* new short-text founder post gets the last 3 same-bucket lessons in the prompt. | Done, prod OFF |
| **E** Observability | Charts, telemetry, accuracy history, runbook | MAE, costs, coverage, and “is learning safe to turn on?”. *Ex:* flat MAE + “F is NO-GO” before you flip toggles. | Done |
| **F** Prove lift | Offline test: need enough error reduction before shipping | Replay history with learning ON vs OFF; need enough MAE drop. *Ex:* ~3% lift vs 5% bar → NO-GO; keep A/D OFF. | NO-GO |
| **G** Smarter lessons | LLM “why” + human review before a lesson is injectable | Richer lesson text must be approved before injection. *Ex:* LLM drafts a “why”; reviewer Approves → injectable. | Staging |
| **H** Meaning match | Embeddings + centroids for better routing / retrieve | Finds “posts like this” beyond exact bucket labels. *Ex:* labeled medium×text but sits near carousel×founders → still pull those lessons. | Staging |
| **I** Scale | Async feedback queue + cluster roll-up summaries | Background jobs + short cluster summaries for volume. *Ex:* drain queue after 40 grades → rollup “CTA late = weak.” | Done |
| **J** Injectability | Shadow mode / softer locks so lessons can move scores | hard_lock (live), soft_blend, shadow_only. *Ex:* shadow logs “would nudge −6” but live score unchanged. | Live = hard lock |
| **G+** Auto-approve | Optionally auto-approve trusted LLM lessons | Skip human review only when trust rules say so. Default OFF. *Ex:* high-confidence templates auto-pass; rest still need a human. | Done, default OFF |

**Safe live defaults:** feedback records ON; calibration OFF; prompt injection OFF;
shadow ON. Do not flip calibration or injection on until Phase **F** is GO.
""",
    ),
    DashboardDocument(
        id="feedback-loop-qna",
        title="Feedback loop Q&A (operator notes)",
        plain_summary=(
            "Plain-English answers: which step writes lessons, holdout vs graded, "
            "switches, buckets, and when to turn on Show lessons to the AI."
        ),
        tags=("feedback", "qna", "operate"),
        body_markdown="""
## Feedback loop Q&A

Notes from operating the Check and learn pages. Safe default reminder:
**Save lessons ON**, **Adjust scores OFF**, **Show lessons to the AI OFF**
until Phase F (offline evaluation) says GO.

---

### Which of the four validation pages writes feedback?

**Feedback loop** — specifically **Write / refresh lessons**
(**Process feedback queue** / **Generate missing feedback**).

**Validation queue** only grades a post and *enqueues* a job when
**Save lessons after grading** is ON. It does not write the lesson itself.

Order: Collect and predict → Validation queue (grade) → Accuracy over time
(charts) → Feedback loop (lessons / learning).

---

### What does “Write / refresh lessons” do?

Stores lessons in Postgres (`prediction_feedback`) and updates learning
buckets (`prediction_clusters`). It does **not** change Collect and predict
by itself.

- **Process feedback queue** — drain pending `feedback_jobs` and write lessons.
- **Generate missing feedback** — backfill graded rows that still lack a v1 lesson.
- Refresh buttons — recompute bucket stats / roll-ups / centroids.

If the queue worker reports `claimed=0`, the queue is empty (lessons already
written or nothing pending).

---

### What does “Rebuild lesson for one post” do?

Overwrites that **one** graded post’s stored lesson JSON and refreshes bucket
stats. It does **not** re-scrape LinkedIn or re-grade actuals. Use after a
template change or to recover a bad/missing lesson.

---

### Holdout vs graded posts?

- **Graded posts** — all validated predictions (the real pile; e.g. ~700).
- **Holdout** — a small fixed sample (e.g. 30) used only by **offline
  evaluation** to replay and compare. It is *not* “how much feedback you have.”

The recent-feedback table on Feedback loop often shows only the last ~30 rows;
that is a display limit, not total stored lessons.

---

### What does Offline evaluation (Phase F) do?

A dry-run report only. It does **not** write lessons and does **not** flip
switches for you.

It replays held-out graded posts with learning ON vs OFF and checks whether
average error drops enough. Reports land as `data/telemetry/eval_feedback_*.json`.

**Read the gates as:**
- Calibration GO → you *may* turn on **Adjust scores from past mistakes**
- Injection GO → you *may* turn on **Show lessons to the AI**
- Otherwise → leave both OFF (safe default)

---

### Is “Show lessons to the AI” correctly OFF?

**Yes — recommended OFF** until Phase F injection is GO. You may already have
many graded posts and stored lessons; that is not the same as *proven lift*.

On **Feedback loop → Operate**, section **2 · Should we turn learning on?**
runs **Phase F · Offline evaluation**. Until that report says GO for
injection, keep **Show lessons to the AI** OFF. Same for **Adjust scores**
until calibration is GO.

---

### If Save lessons is ON, does Collect and predict get the feedback?

**No.** That switch only **creates** lessons after grading.

Collect and predict only uses them when:

- **Show lessons to the AI** is ON (prompt injection), and/or
- **Adjust scores from past mistakes** is ON (numeric calibration nudge).

---

### Where do lessons “go”? Folders?

Not folders. Postgres:

| Store | Role |
|-------|------|
| `feedback_jobs` | Queue after validate |
| `prediction_feedback` | Lesson rows |
| `prediction_clusters` | Learning buckets + stats |

Browse buckets on **Feedback loop → Understand learning**. Human-readable
export: `data/feedback_readable.md`.

---

### How are learning buckets sorted / named?

Buckets are `length × format × follower band`
(e.g. `medium_prose_unknown`). The table is usually ordered by **samples**
(most → least). `ready` means enough samples for cluster calibration;
`need 50` means the bucket is still thin.

---

### Can more learning bucket types be made?

**Not freely in the UI.** New combinations appear automatically when posts
match a new length/format/follower band. New axes (topic, industry, etc.)
need a code change to the routing rules.

---

### Do learning switches rewrite the three earlier steps?

Mostly **no** on past runs. They affect:

- **Save lessons** — whether validate enqueues / writes new lessons.
- **Calibration / Show lessons** — the **next** Collect and predict run.

Validation queue and Accuracy over time stay grading + charts; switches do
not rewrite that history.

---

### Quick operator checklist

1. Collect and predict → queue posts.
2. Validation queue → grade (enqueues lesson jobs if Save lessons is ON).
3. Feedback loop → **Process feedback queue** (or Generate missing).
4. Phase F offline evaluation → prove lift before flipping injection / calibration.
5. Only then consider **Show lessons to the AI** / **Adjust scores**.
""",
    ),
)


def get_document(doc_id: str) -> DashboardDocument | None:
    for doc in DOCUMENTS:
        if doc.id == doc_id:
            return doc
    return None
