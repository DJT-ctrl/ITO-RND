-- A2: corpus topic-drift / trend radar (offline weekly batch).
-- Applied via storage.schema_modules.apply_module_schemas().

CREATE TABLE IF NOT EXISTS trends (
    trend_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start              DATE NOT NULL,
    cluster_id              TEXT NOT NULL,
    label                   TEXT NOT NULL DEFAULT '',
    post_count              INTEGER NOT NULL CHECK (post_count >= 0),
    share_of_corpus         DOUBLE PRECISION NOT NULL,
    growth_rate             DOUBLE PRECISION,
    mean_total_engagement   DOUBLE PRECISION,
    example_post_ids        TEXT[] NOT NULL DEFAULT '{}',
    centroid                vector(3072),
    source                  TEXT NOT NULL DEFAULT 'corpus',
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trends_source_chk CHECK (source IN ('corpus'))
);

CREATE UNIQUE INDEX IF NOT EXISTS trends_week_cluster_uidx
    ON trends (week_start, cluster_id);

CREATE INDEX IF NOT EXISTS trends_week_start_idx
    ON trends (week_start DESC);

CREATE INDEX IF NOT EXISTS trends_growth_rate_idx
    ON trends (growth_rate DESC NULLS LAST);
