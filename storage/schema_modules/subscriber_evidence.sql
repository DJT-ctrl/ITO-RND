-- Phase 19: subscriber-specific evidence briefs, reviewed plans, scoped
-- evidence membership, collection jobs, and receipts.
-- Release A describes plans; Release B executes them under fixed caps.
-- These rows do not authorize a scrape by themselves — approval + worker do.

CREATE TABLE IF NOT EXISTS subscriber_evidence_briefs (
    id                          TEXT PRIMARY KEY,
    subscriber_id               TEXT NOT NULL UNIQUE,
    public_profile_url          TEXT NOT NULL,
    profile_authorized          BOOLEAN NOT NULL CHECK (profile_authorized),
    role_description            TEXT NOT NULL,
    primary_niche               TEXT NOT NULL,
    sub_niche                   TEXT NOT NULL DEFAULT '',
    target_audience             TEXT NOT NULL,
    objectives                  TEXT[] NOT NULL DEFAULT '{}',
    locale                      TEXT NOT NULL DEFAULT '',
    seed_accounts               TEXT[] NOT NULL DEFAULT '{}',
    status                      TEXT NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'approved', 'paused')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subscriber_baseline_plans (
    id                          TEXT PRIMARY KEY,
    brief_id                    TEXT NOT NULL REFERENCES subscriber_evidence_briefs(id)
                                ON DELETE CASCADE,
    provider                    TEXT NOT NULL DEFAULT 'apify',
    baseline_budget_usd         NUMERIC(10, 2) NOT NULL DEFAULT 10.00
                                CHECK (baseline_budget_usd >= 0 AND baseline_budget_usd <= 10.00),
    daily_candidate_limit       INTEGER NOT NULL DEFAULT 100
                                CHECK (daily_candidate_limit BETWEEN 1 AND 100),
    source_priorities           TEXT[] NOT NULL DEFAULT '{}',
    proposed_queries            TEXT[] NOT NULL DEFAULT '{}',
    rationale                   TEXT NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'proposed'
                                CHECK (status IN ('proposed', 'approved', 'superseded')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at                 TIMESTAMPTZ
);

-- Release A initially had UNIQUE(brief_id), which blocked revise/supersede history.
ALTER TABLE subscriber_baseline_plans
    DROP CONSTRAINT IF EXISTS subscriber_baseline_plans_brief_id_key;

CREATE INDEX IF NOT EXISTS subscriber_baseline_plans_brief_id_idx
    ON subscriber_baseline_plans (brief_id);

CREATE INDEX IF NOT EXISTS subscriber_evidence_briefs_status_idx
    ON subscriber_evidence_briefs (status);

CREATE INDEX IF NOT EXISTS subscriber_baseline_plans_status_idx
    ON subscriber_baseline_plans (status);

-- Release B: normalized evidence candidates with provenance.
CREATE TABLE IF NOT EXISTS subscriber_evidence_items (
    id                          TEXT PRIMARY KEY,
    post_id                     TEXT,
    source_url                  TEXT,
    source_type                 TEXT NOT NULL DEFAULT 'unknown'
                                CHECK (source_type IN (
                                    'subscriber_public_profile',
                                    'approved_seed_accounts',
                                    'niche_keyword_queries',
                                    'shared_niche_corpus',
                                    'unknown'
                                )),
    content_preview             TEXT NOT NULL DEFAULT '',
    primary_niche               TEXT NOT NULL DEFAULT '',
    sub_niche                   TEXT NOT NULL DEFAULT '',
    target_audience             TEXT NOT NULL DEFAULT '',
    author_key                  TEXT NOT NULL DEFAULT '',
    quality_score               NUMERIC(6, 3),
    decision                    TEXT NOT NULL
                                CHECK (decision IN ('accepted', 'rejected')),
    rejection_reason            TEXT,
    provider_run_id             TEXT,
    collection_job_id           TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS subscriber_evidence_items_post_id_idx
    ON subscriber_evidence_items (post_id)
    WHERE post_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS subscriber_evidence_membership (
    subscriber_id               TEXT NOT NULL,
    evidence_id                 TEXT NOT NULL REFERENCES subscriber_evidence_items(id)
                                ON DELETE CASCADE,
    scope                       TEXT NOT NULL
                                CHECK (scope IN ('subscriber_private', 'shared_niche')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subscriber_id, evidence_id, scope)
);

CREATE INDEX IF NOT EXISTS subscriber_evidence_membership_subscriber_idx
    ON subscriber_evidence_membership (subscriber_id, scope);

CREATE TABLE IF NOT EXISTS subscriber_collection_jobs (
    id                          TEXT PRIMARY KEY,
    subscriber_id               TEXT NOT NULL,
    brief_id                    TEXT NOT NULL REFERENCES subscriber_evidence_briefs(id)
                                ON DELETE CASCADE,
    plan_id                     TEXT NOT NULL REFERENCES subscriber_baseline_plans(id)
                                ON DELETE CASCADE,
    job_kind                    TEXT NOT NULL
                                CHECK (job_kind IN ('baseline', 'daily_refresh')),
    gap_reason                  TEXT NOT NULL DEFAULT '',
    status                      TEXT NOT NULL DEFAULT 'planned'
                                CHECK (status IN (
                                    'planned', 'running', 'completed', 'failed', 'skipped'
                                )),
    estimated_cost_usd          NUMERIC(10, 4) NOT NULL DEFAULT 0,
    actual_cost_usd             NUMERIC(10, 4) NOT NULL DEFAULT 0,
    candidate_count             INTEGER NOT NULL DEFAULT 0,
    accepted_count              INTEGER NOT NULL DEFAULT 0,
    rejected_count              INTEGER NOT NULL DEFAULT 0,
    recommended_seeds           TEXT[] NOT NULL DEFAULT '{}',
    error_detail                TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at                  TIMESTAMPTZ,
    finished_at                 TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS subscriber_collection_jobs_subscriber_idx
    ON subscriber_collection_jobs (subscriber_id, created_at DESC);

CREATE TABLE IF NOT EXISTS subscriber_evidence_receipts (
    id                          TEXT PRIMARY KEY,
    subscriber_id               TEXT NOT NULL,
    collection_job_id           TEXT NOT NULL REFERENCES subscriber_collection_jobs(id)
                                ON DELETE CASCADE,
    collected_count             INTEGER NOT NULL DEFAULT 0,
    rejected_count              INTEGER NOT NULL DEFAULT 0,
    actual_cost_usd             NUMERIC(10, 4) NOT NULL DEFAULT 0,
    coverage_gaps               TEXT[] NOT NULL DEFAULT '{}',
    next_refresh_at             TIMESTAMPTZ,
    summary                     TEXT NOT NULL DEFAULT '',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS subscriber_evidence_receipts_subscriber_idx
    ON subscriber_evidence_receipts (subscriber_id, created_at DESC);

-- Tracks remaining baseline spend and daily candidate usage per subscriber.
CREATE TABLE IF NOT EXISTS subscriber_evidence_budget_ledger (
    subscriber_id               TEXT NOT NULL,
    plan_id                     TEXT NOT NULL,
    day                         DATE NOT NULL,
    baseline_spent_usd          NUMERIC(10, 4) NOT NULL DEFAULT 0,
    daily_candidates            INTEGER NOT NULL DEFAULT 0,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subscriber_id, plan_id, day)
);
