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
| 8 | **Don't create more issues by accident** — before implementing, check whether the planned fix would create new bugs, deficits, or follow-on work; if yes, stop and ask the user | Team request |

---

## Side-effect check (do this before coding)

Before branching/implementing the current issue, briefly look for whether solving it
could **create more issues** (new bugs, missing follow-ups, broken assumptions,
new ops debt, or work that is not already in [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md)).

Ask yourself:

- Does this change leave a half-finished dependency (e.g. infra without runbook)?
- Could it break an existing path or invalidate another open issue's assumptions?
- Are we introducing a capability that needs a new GitHub issue to be safe/complete?
- Is the “missing piece” already covered by an open backlog issue? Prefer linking that over inventing more.

**If you find one (or more):**

1. **Do not** open new GitHub issues, expand scope, or keep implementing past the stop point.
2. End your reply with a **bold** callout after the main answer, then ask permission:

> **Possible new issue if we proceed:** \<one-line description\>.  
> Already covered by backlog #N? yes/no.  
> May I proceed with the current issue only, or do you want to adjust scope first?

3. Wait for the user's explicit permission before continuing.

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
| Issue #14 | PR → HTTPS + strict SGs (WAF deferred) |
| Issue #17 | PR → WAFv2 + exception runbook |
| Issue #19 | Branch `feature/issue-19-ec2-ebs-rightsizing` — rightsizing + idle policy |
| Issue #16 | PR → CloudWatch logs/alarms MVP |
| Issue #18 | PR → AWS Budgets + cost playbook |
| Issue #20 | PR → deploy/rollback runbook |
| Issues #2–#27 | Still open — see [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) |
| Next suggested | After #1 merges: next **P0** (#3 auth/rate-limit, or #13/#15 AWS) |

Update [`ISSUE_BACKLOG.md`](ISSUE_BACKLOG.md) when issues close.

---

## What “done” looks like for each issue

```
1. Confirm or create GitHub issue on intotheopen/intotheopen-backend
2. Side-effect check — if solving this could create more issues, bold callout + ask user before coding
3. Branch from main: fix/issue-N-short-slug
4. Implement + pytest
5. PR to intotheopen/intotheopen-backend with Closes #N + clear test plan
6. Request review (Tech Lead / CTO) — merge after 1 approval
7. Tick ISSUE_BACKLOG.md
```

Do **not** batch unrelated issues into one PR.
Do **not** open extra GitHub issues without the user's permission.
