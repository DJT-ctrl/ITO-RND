# Git & Issue Workflow Reminder

**For:** Humans and AI agents working in this repository  
**Last updated:** 2026-07-16  
**New to git/GitHub?** Start with [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)

**Official org workflow:** [intotheopen/.github](https://github.com/intotheopen/.github) — [CONTRIBUTING.md](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md), [BACKEND.md](https://github.com/intotheopen/.github/blob/main/BACKEND.md), [PR template](https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md)

---

## Core rules (read before opening any PR)

### 1. Issue first — never PR-only for bugs, improvements, or deficits

Do **not** open a pull request directly for:

- **Bugs** — something broken or incorrect
- **Improvements** — enhancements, hardening, refactors with user-facing impact
- **Deficits** — missing capability, documentation gap, operational gap

**Instead:**

1. Check whether an issue already exists ([ISSUE_BACKLOG.md](ISSUE_BACKLOG.md) or [GitHub Issues](https://github.com/intotheopen/intotheopen-backend/issues)).
2. If none exists, **create a GitHub issue first** with a clear title, description, acceptance criteria, and labels.
3. Only then branch and implement.

Exception: trivial typo-only doc fixes may go straight to PR if the team agrees — when in doubt, open an issue.

### 2. Every PR must reference its issue

When you open a PR, **always** state which issue it solves:

- In the PR title: `fix: stabilize agent provider init (#1)`  
- In the PR body: `Closes #1` or `Fixes #1` (or `Relates to #N` for partial work)

One PR should map to **one** primary issue unless the issues are explicitly bundled and agreed in advance.

### 3. One PR per solution

- **27 open issues** need to be resolved ([ISSUE_BACKLOG.md](ISSUE_BACKLOG.md)).
- **Create a separate PR for each solution** — small, focused, reviewable.
- Do not mix unrelated fixes in one PR (see also [08 — Build Practices](../planning/validation-feedback-loop/08_BUILD_PRACTICES.md): *"Scope each PR to one concern"*).

### 4. Clear explanations

Each PR description must include:

| Section | What to write |
| ------- | ------------- |
| **Summary** | What changed and why (1–3 bullets) |
| **Issue** | Link: `Closes #N` |
| **How to test** | Concrete steps or commands |
| **Risks / rollback** | Anything ops or reviewers should know |

**Do not** append tool watermarks to PR descriptions (e.g. `Made with [Cursor](https://cursor.com)`).
GitHub/Cursor may add these automatically — remove them before requesting review.

When work grows beyond a single PR, update the issue with progress notes so we can see **what was done and why** without re-reading every diff.

### 5. Org git rules (from intotheopen/.github)

From the [org CONTRIBUTING guide](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md):

- **Never push directly to `main`** — branch protection is on; all changes go through a PR
- **Branch naming** (adapt `Task_ID` → issue number for this repo):

| Type | Pattern | Example |
| ---- | ------- | ------- |
| Feature | `feature/issue-N-short-slug` | `feature/issue-5-ci-quality-gates` |
| Bug fix | `fix/issue-N-short-slug` | `fix/issue-1-agent-provider-init` |
| Infra | `infra/short-slug` | `infra/aws-budget-alerts` |
| Chore/docs | `chore/short-slug` | `chore/update-readme` |

- **PR process:** branch → commit → open PR (use [PR template](https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md)) → request review → merge after **1 approval** and passing local builds

---

## Suggested workflow

```
1. Pick issue from backlog (or create issue if missing)
2. Comment on issue: "Taking this" / assign yourself
3. Branch:  fix/issue-N-short-slug  (see org naming above)
4. Implement + tests (pytest -q)
5. Open PR with Closes #N + PR template checklist
6. Review → merge → issue auto-closes
7. Tick issue in ISSUE_BACKLOG.md
```

---

## Commit messages

Follow conventional commits and reference issues where helpful:

```
fix(agents): lazy-init provider to avoid import crash

Closes #1
```

Prefixes: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `infra`.

---

## When things get bigger

As the backlog shrinks or scope expands:

1. **Re-read the issue** — acceptance criteria may have shifted.
2. **Check [ISSUE_BACKLOG.md](ISSUE_BACKLOG.md)** — what is done vs open, and priority labels (`P0`, `P1`, `P2`).
3. **Check planning docs** — especially [`08_BUILD_PRACTICES.md`](../planning/validation-feedback-loop/08_BUILD_PRACTICES.md) for module boundaries, test expectations, and anti-patterns.
4. **Check org docs** — [intotheopen/.github](https://github.com/intotheopen/.github) for branching, PR template, and backend architecture notes.
5. **Do not batch unrelated issues** into one PR to "save time" — it makes review and rollback harder.

---

## Priority guidance (from issue labels)

| Label | Meaning |
| ----- | ------- |
| `priority:P0` | Do first — security, crash, data loss risk |
| `priority:P1` | Stabilization / launch blockers |
| `priority:P2` | Post-launch hardening, performance, nice-to-have |

Phases on issues: `phase:stabilization` → AWS MVP → `phase:post-launch-hardening`.

---

## Quick links

| Resource | URL |
| -------- | --- |
| Beginner walkthrough | [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md) |
| 27-issue checklist | [ISSUE_BACKLOG.md](ISSUE_BACKLOG.md) |
| Open issues on GitHub | https://github.com/intotheopen/intotheopen-backend/issues |
| Org workflow hub | https://github.com/intotheopen/.github |
| Org contributing rules | https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md |
| Org PR template | https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md |
| Build practices (this repo) | [08_BUILD_PRACTICES.md](../planning/validation-feedback-loop/08_BUILD_PRACTICES.md) |
| Deploy / runbook | [deploy/README.md](../deploy/README.md) |
