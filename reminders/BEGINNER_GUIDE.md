# Beginner guide — how we fix things in this repo

**You said you're new to this — that's fine.** This doc explains the whole process in plain language.

**Official org docs (read when you want more detail):**

- [intotheopen/.github — README](https://github.com/intotheopen/.github) — org overview, git workflow, branch names
- [intotheopen/.github — CONTRIBUTING.md](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md) — branch naming + PR steps
- [intotheopen/.github — BACKEND.md](https://github.com/intotheopen/.github/blob/main/BACKEND.md) — backend repo layout (this project is the backend)
- [PR template](https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md) — what to fill in when you open a PR

---

## The three things you need to understand

| Term | What it is | Analogy |
| ---- | ---------- | ------- |
| **Issue** | A ticket on GitHub describing a bug or task | A sticky note on the team board: "Fix the door that won't close" |
| **Branch** | Your own copy of the code to work on safely | A scratch pad — you don't write on the master copy |
| **Pull Request (PR)** | "Please merge my changes into main" | Handing in homework for review before it goes in the textbook |

**Golden rule for this project:** always have an **issue** before you open a **PR**.

---

## The full workflow (step by step)

### Step 1 — Pick or create an issue

1. Open the [issue backlog](ISSUE_BACKLOG.md) or [GitHub Issues](https://github.com/intotheopen/intotheopen-backend/issues).
2. We have **27 open issues** (#1–#27). Pick one (start with **P0** if unsure).
3. If the problem isn't listed yet, **create a new issue first** — don't jump straight to code.

**What goes in a good issue:**

- What's wrong or what's missing
- What "done" looks like (acceptance criteria)
- Labels if you know them (`bug`, `enhancement`, `priority:P0`, etc.)

### Step 2 — Create a branch (never work on `main` directly)

The [org contributing guide](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md) says:

> Never commit or push directly to `main`.

Branch off `main` using one of these patterns. For **this repo**, use the **issue number** where the org docs say `Task_ID`:

| Type | Branch name pattern | Example for issue #1 |
| ---- | ------------------- | -------------------- |
| Bug fix | `fix/issue-N-short-slug` | `fix/issue-1-agent-provider-init` |
| New feature | `feature/issue-N-short-slug` | `feature/issue-5-ci-quality-gates` |
| Infra / DevOps | `infra/short-slug` | `infra/aws-budget-alerts` |
| Docs / chores | `chore/short-slug` | `chore/update-readme` |

```bash
git checkout main
git pull
git checkout -b fix/issue-1-agent-provider-init
```

### Step 3 — Make your changes and commit

- Change only what the **one issue** needs (one issue → one PR).
- Run tests: `pytest -q`
- Commit with a clear message:

```bash
git add <files you changed>
git commit -m "fix(agents): lazy-init provider to avoid import crash

Closes #1"
```

### Step 4 — Push and open a Pull Request

```bash
git push -u origin fix/issue-1-agent-provider-init
```

Then on GitHub: **New Pull Request** → base: `main` ← your branch.

**PR title example:** `fix: stabilize agent provider initialization (#1)`

**PR body must include:**

```markdown
Closes #1

## Summary
- What you changed and why (1–3 bullets)

## How to test
- Commands or steps someone can run to verify

## Risks / rollback
- Anything that could break; how to undo if needed
```

Do **not** add `Made with Cursor` or other editor watermarks to the PR body.

Also use the org [PR template checklist](https://github.com/intotheopen/.github/blob/main/.github/PULL_REQUEST_TEMPLATE.md):

- [ ] Branch naming follows convention
- [ ] Tests pass locally (`pytest -q`)
- [ ] Env / settings updated if needed
- [ ] DB migrations included if you changed schema
- [ ] Docker builds if you touched deploy (`docker compose up --build`)

### Step 5 — Get review and merge

Per org workflow:

1. Request review from Tech Lead / CTO
2. Wait for **1 approval**
3. Confirm builds/tests pass
4. Merge — GitHub will **close the issue** automatically if you wrote `Closes #N`

### Step 6 — Track progress

- Tick the issue in [ISSUE_BACKLOG.md](ISSUE_BACKLOG.md) when it's closed
- If the fix was bigger than expected, add a comment on the issue explaining **what was done and why**

---

## Rules we agreed on (short version)

1. **Issue first** — no PR for a bug, improvement, or gap without an issue
2. **Link the issue** — every PR says `Closes #N`
3. **One PR per issue** — 27 issues, 27 separate solutions (don't bundle unrelated fixes)
4. **Clear explanations** — reviewer should understand without reading every line of code
5. **Never push to `main`** — always go through a PR ([org rule](https://github.com/intotheopen/.github/blob/main/.github/CONTRIBUTING.md))

---

## What issue priority means

| Label | Meaning | Examples in our backlog |
| ----- | ------- | ----------------------- |
| `priority:P0` | Do first — crashes, security, data loss | #1, #3, #13, #15 |
| `priority:P1` | Important for stabilization / launch | Most of #2–#27 |
| `priority:P2` | Can wait until after launch | #8, #14, #17, #19, #21, #22 |

Full list: [ISSUE_BACKLOG.md](ISSUE_BACKLOG.md)

---

## Glossary

| Word | Meaning |
| ---- | ------- |
| `main` | The official branch everyone shares — protected, no direct pushes |
| `origin` | Your GitHub remote (where you push branches) |
| `Closes #N` | Magic phrase in a PR — merges close issue #N on GitHub |
| `pytest` | Runs automated tests to check nothing broke |
| `conventional commit` | Commit prefix like `fix:`, `feat:`, `chore:` — helps history stay readable |

---

## Where to go next

| I want to… | Read this |
| ---------- | --------- |
| See all 27 issues | [ISSUE_BACKLOG.md](ISSUE_BACKLOG.md) |
| Full workflow rules (agents + humans) | [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) |
| How to structure code in a PR | [08_BUILD_PRACTICES.md](../planning/validation-feedback-loop/08_BUILD_PRACTICES.md) |
| Org git & branching rules | [intotheopen/.github](https://github.com/intotheopen/.github) |
| Run the app locally | [README.md](../README.md) |
