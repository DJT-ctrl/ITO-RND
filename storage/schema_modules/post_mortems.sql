-- A1: anomaly post-mortem case studies (offline batch consumer).
-- Applied via storage.schema_modules.apply_module_schemas().

CREATE TABLE IF NOT EXISTS post_mortems (
    post_mortem_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id             TEXT NOT NULL REFERENCES posts(post_id),
    machine_reasons     TEXT[] NOT NULL DEFAULT '{}',
    verdict             TEXT NOT NULL,
    summary             TEXT NOT NULL,
    evidence            JSONB NOT NULL DEFAULT '{}',
    lesson_for_models   TEXT NOT NULL,
    model               TEXT NOT NULL DEFAULT '',
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT post_mortems_verdict_chk CHECK (
        verdict IN (
            'likely_inorganic',
            'plausible_organic_outlier',
            'ambiguous',
            'data_quality'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS post_mortems_post_id_uidx
    ON post_mortems (post_id);

CREATE INDEX IF NOT EXISTS post_mortems_verdict_idx
    ON post_mortems (verdict);

CREATE INDEX IF NOT EXISTS post_mortems_generated_at_idx
    ON post_mortems (generated_at DESC);
