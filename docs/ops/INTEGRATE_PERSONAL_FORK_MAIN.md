# Integrate branch: personal fork `main` → org review

**Org branch:** `integrate/personal-fork-main`  
**Org remote:** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)  
**Source:** Kevin’s personal fork line ([DJT-ctrl/ITO-RND](https://github.com/DJT-ctrl/ITO-RND)) local `main`, after merging Erdal’s infra/API work onto the feature-complete fork `main`.

## What this is

This is **not** org `main`. It is a **review branch** that packages Kevin’s personal/fork `main` (Phase 11, agentic layer, audience critic, synthesis, trend radar, post-mortems, dashboard split to `dashboard-for-devs`, plus infra/API already present on org) so the team can review and merge into **org `main` later**.

As of branch creation, this tip **already contains** current `intotheopen/main` as an ancestor (superset), then adds the product/feature commits that lived only on the fork integrate line.

## Remotes (this checkout)

| Remote | URL | Use |
| ------ | --- | --- |
| `intotheopen` | `https://github.com/intotheopen/intotheopen-backend.git` | **Canonical.** Active work tracks `integrate/personal-fork-main` until merged; then org `main` via PR only. |
| `origin` | `https://github.com/DJT-ctrl/ITO-RND.git` | Personal fork (historical). Do not treat as team source of truth. |
| `collaborator` | `hmabubakar313/ITO-RND` | Collaborator fork — not canonical. |

## Working rules while this PR is open

1. **Commit and push to** `intotheopen/integrate/personal-fork-main` (this branch), not to personal-fork `main`, and **never** push directly to org `main`.
2. After the team **merges this branch into org `main`**, new work goes through normal issue → branch → PR into **org `main`** (see `reminders/GIT_ISSUE_WORKFLOW.md`).
3. Do not reintroduce a Streamlit `dashboard/` package into the backend; ops UI lives in `dashboard-for-devs`.

## How to update this branch

```bash
git fetch intotheopen
git checkout integrate/personal-fork-main
git pull intotheopen integrate/personal-fork-main
# … commit work …
git push intotheopen HEAD
```

## Review / merge later

Open or use the draft PR from `integrate/personal-fork-main` → `main` on `intotheopen/intotheopen-backend`. Merge only after team review.
