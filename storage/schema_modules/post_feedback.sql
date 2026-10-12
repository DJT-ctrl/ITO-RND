-- Detailed AI feedback for stored posts (offline batch).
-- Applied via storage.schema_modules.apply_module_schemas().
-- Does not feed the live predictor. Review status starts pending.

CREATE TABLE IF NOT EXISTS post_feedback (
    post_feedback_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id             TEXT NOT NULL REFERENCES posts(post_id),
    summary             TEXT NOT NULL,
    what_worked         TEXT[] NOT NULL DEFAULT '{}',
    what_to_change      TEXT[] NOT NULL DEFAULT '{}',
    neighbor_notes      JSONB NOT NULL DEFAULT '[]',
    evidence            JSONB NOT NULL DEFAULT '{}',
    review_status       TEXT NOT NULL DEFAULT 'pending',
    reviewed_at         TIMESTAMPTZ,
    reviewed_by         TEXT,
    model               TEXT NOT NULL DEFAULT '',
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT post_feedback_review_status_chk CHECK (
        review_status IN ('pending', 'approved', 'rejected')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS post_feedback_post_id_uidx
    ON post_feedback (post_id);

CREATE INDEX IF NOT EXISTS post_feedback_review_status_idx
    ON post_feedback (review_status);

CREATE INDEX IF NOT EXISTS post_feedback_generated_at_idx
    ON post_feedback (generated_at DESC);
