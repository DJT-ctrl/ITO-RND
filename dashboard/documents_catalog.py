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

| Phase | Plain English | Status (as of redesign) |
|-------|---------------|-------------------------|
| **0** Foundation | Grade predictions once real engagement exists | Done |
| **A** Calibration | Nudge predicted percentile using past errors | Done, prod OFF |
| **B** Lessons | After grading, store a short template lesson | Done |
| **C** Buckets | Route posts into length × format × audience groups | Done |
| **D** Injection | Put recent same-bucket lessons into the predictor prompt | Done, prod OFF |
| **E** Observability | Charts, telemetry, accuracy history, runbook | Done |
| **F** Prove lift | Offline test: need enough error reduction before shipping | NO-GO |
| **G** Smarter lessons | LLM “why” + human review before a lesson is injectable | Staging |
| **H** Meaning match | Embeddings + centroids for better routing / retrieve | Staging |
| **I** Scale | Async feedback queue + cluster roll-up summaries | Done |
| **J** Injectability | Shadow mode / softer locks so lessons can move scores | Live = hard lock |

**Safe live defaults:** feedback records ON; calibration OFF; prompt injection OFF;
shadow ON. Do not flip calibration or injection on until Phase **F** is GO.
""",
    ),
)


def get_document(doc_id: str) -> DashboardDocument | None:
    for doc in DOCUMENTS:
        if doc.id == doc_id:
            return doc
    return None
