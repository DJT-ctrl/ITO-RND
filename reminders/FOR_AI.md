# AI context pack — issue & PR workflow

**Point Cursor (or any AI) at this whole folder:** `@reminders`

This folder is the source of truth for how we fix bugs and ship PRs on
**intotheopen/intotheopen-backend**. Follow these docs before writing code.

---

## Read order (for AI agents)

1. **This file** — mission rules (below)
2. [`GIT_ISSUE_WORKFLOW.md`](GIT_ISSUE_WORKFLOW.md) — detailed rules
3. [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) — which issues exist / priority
4. [`BEGINNER_GUIDE.md`](BEGINNER_GUIDE.md) — plain-language walkthrough (for humans)
5. Org docs (authoritative team process):
   - https://github.com/intotheopen/.github
   - https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md
   - https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md
   - https://github.com/intotheopen/.github/blob/main/BACKEND.md

---

## Non-negotiable rules (manager + org)

| # | Rule | Source |
| - | ---- | ------ |
| 1 | **Issue first** — do not open a PR for a bug, improvement, or deficit without a GitHub issue | Team request |
| 2 | **Every PR links its issue** — title has `(#N)`, body has `Closes #N` | Team request |
| 3 | **One PR per issue** — separate PR for each of the ~27 solutions; clear explanations | Team request |
| 4 | **Never push to `main`** — branch → PR → 1 approval → merge | [org CONTRIBUTING](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md) |
| 5 | **Branch naming** — `fix/issue-N-slug`, `feature/issue-N-slug`, `infra/…`, `chore/…` | Org + this folder |
| 6 | **Small focused PRs** — one concern; use org PR template checklist | Org + [`08_BUILD_PRACTICES`](../planning/validation-feedback-loop/08_BUILD_PRACTICES.md) |
| 7 | **No Cursor watermark in PRs** — never append `Made with Cursor` (or similar) to PR bodies or issue comments | Team request |

---

## Canonical repositories

| Role | Repo |
| ---- | ---- |
| **Issues + PRs (use this)** | https://github.com/intotheopen/intotheopen-backend |
| Org workflow hub | https://github.com/intotheopen/.github |
| Personal fork (optional push target) | https://github.com/DJT-ctrl/ITO-RND |

When fetching issues: `gh issue view N --repo intotheopen/intotheopen-backend`

---

## Current progress snapshot

| Item | Status |
| ---- | ------ |
| Issue #1 | PR open → https://github.com/intotheopen/intotheopen-backend/pull/29 (`Closes #1`) |
| Issues #2–#27 | Still open — see [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) |
| Next suggested | After #1 merges: next **P0** (#3 auth/rate-limit, or #13/#15 AWS) |

Update [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) when issues close.

---

## What “done” looks like for each issue

```
1. Confirm or create GitHub issue on intotheopen/intotheopen-backend
2. Branch from main: fix/issue-N-short-slug
3. Implement + pytest
4. PR to intotheopen/intotheopen-backend with Closes #N + clear test plan
5. Request review (Tech Lead / CTO) — merge after 1 approval
6. Tick ISSUE_BACKLOG.md
```

Do **not** batch unrelated issues into one PR.
