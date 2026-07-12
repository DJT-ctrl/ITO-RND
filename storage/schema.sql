-- T1.4/T1.5: posts table + pgvector column + HNSW index.
--
-- Mirrors processors/schemas.py's NormalizedPost field-for-field (plus
-- `content`, re-joined from data/raw/ the same way run_embeddings.py does
-- it, and `embedding`, produced by processors/embedder.py) so downstream
-- queries can filter/sort on engagement or content-shape fields without a
-- separate lookup.
--
-- Applied by storage/vector_store.create_schema() — this file is also kept
-- standalone so it can be run directly with psql for manual inspection:
--   docker exec -it <container> psql -U ito -d ito_posts -f /schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS posts (
    -- 1. Identity / join keys
    post_id             TEXT PRIMARY KEY,
    author_public_id    TEXT NOT NULL DEFAULT '',
    linkedin_url        TEXT NOT NULL DEFAULT '',
    -- Tenant scoping (personalization): which subscriber this post belongs
    -- to, so retrieval/voice-profile queries can be filtered per-user.
    -- NULL = a global-corpus post (e.g. the bulk-scraped dataset ingested
    -- so far), not owned by any particular subscriber.
    user_id             TEXT,

    -- 2. Raw engagement counts
    likes               INTEGER NOT NULL CHECK (likes >= 0),
    comments            INTEGER NOT NULL CHECK (comments >= 0),
    shares              INTEGER NOT NULL CHECK (shares >= 0),
    total_engagement    INTEGER NOT NULL CHECK (total_engagement >= 0),
    comment_ratio       DOUBLE PRECISION,
    share_ratio         DOUBLE PRECISION,

    -- 3. Content shape
    word_count          INTEGER NOT NULL CHECK (word_count >= 0),
    char_count          INTEGER NOT NULL CHECK (char_count >= 0),
    hashtag_count       INTEGER NOT NULL CHECK (hashtag_count >= 0),
    emoji_count         INTEGER NOT NULL CHECK (emoji_count >= 0),
    has_media           BOOLEAN NOT NULL,
    is_job_post         BOOLEAN NOT NULL,

    -- 4. Timing
    hour_of_day         SMALLINT CHECK (hour_of_day BETWEEN 0 AND 23),
    day_of_week         TEXT,

    -- 5. Engagement benchmark
    engagement_percentile DOUBLE PRECISION NOT NULL CHECK (engagement_percentile BETWEEN 0 AND 100),
    engagement_zscore      DOUBLE PRECISION NOT NULL,
    engagement_rate         DOUBLE PRECISION,
    -- Optional follower-normalization (T6 Point 1, processors/run_pipeline.py
    -- --with-profile-enrichment). All nullable: only populated when that
    -- opt-in path ran AND a given author's follower count was resolved
    -- (partial coverage is expected, not an error).
    follower_count          INTEGER CHECK (follower_count >= 0),
    author_location_text    TEXT,
    author_timezone         TEXT,
    audience_adjusted_percentile DOUBLE PRECISION CHECK (audience_adjusted_percentile BETWEEN 0 AND 100),
    audience_adjusted_zscore      DOUBLE PRECISION,

    -- 6. Qualitative tags (Stage 2 - Gemini, optional)
    hook_type           TEXT,
    tone                TEXT,
    topic               TEXT,
    has_explicit_cta    BOOLEAN,
    writing_style       TEXT,

    -- 7. Anomaly detection (batch step, processors/benchmark.py)
    engagement_anomaly_flag BOOLEAN NOT NULL DEFAULT FALSE,
    anomaly_reasons         TEXT[] NOT NULL DEFAULT '{}',

    -- 8. Raw text + embedding (T1.3 output)
    content             TEXT NOT NULL,
    embedding           vector(3072) NOT NULL,

    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration for pre-existing tables: CREATE TABLE IF NOT EXISTS above is a
-- no-op once the table already exists, so a table created before the
-- anomaly-detection columns were added (group 7) would otherwise never
-- get them. ADD COLUMN IF NOT EXISTS is idempotent/safe to re-run and a
-- no-op on a freshly-created table (columns already exist from the CREATE
-- TABLE above).
ALTER TABLE posts ADD COLUMN IF NOT EXISTS engagement_anomaly_flag BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS anomaly_reasons TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE posts ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS follower_count INTEGER;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_location_text TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_timezone TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS audience_adjusted_percentile DOUBLE PRECISION;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS audience_adjusted_zscore DOUBLE PRECISION;

-- Speeds up tenant-scoped retrieval (WHERE user_id = ...) and the voice-
-- profile aggregation query in storage/vector_store.get_user_voice_profile().
CREATE INDEX IF NOT EXISTS posts_user_id_idx ON posts (user_id) WHERE user_id IS NOT NULL;

-- T6.6: profiles scrape cache — one row per author_public_id so profile
-- scrapes aren't repeated across pipeline runs (see storage/profile_store.py).
CREATE TABLE IF NOT EXISTS profiles (
    author_public_id    TEXT PRIMARY KEY,
    follower_count      INTEGER CHECK (follower_count >= 0),
    connections_count   INTEGER,
    headline            TEXT,
    location_text       TEXT,
    is_business         BOOLEAN NOT NULL DEFAULT FALSE,
    linkedin_url        TEXT,
    scraped_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS profiles_scraped_at_idx ON profiles (scraped_at);

-- Prediction validation pipeline: tracked live posts with scheduled re-scrape.
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    linkedin_post_id        TEXT NOT NULL,
    linkedin_url            TEXT NOT NULL,
    author_public_id        TEXT NOT NULL DEFAULT '',
    content                 TEXT NOT NULL,
    posted_at               TIMESTAMPTZ NOT NULL,

    predicted_engagement_percentile  DOUBLE PRECISION NOT NULL,
    predicted_total_engagement       INTEGER,
    predicted_likes                  INTEGER,
    predicted_comments               INTEGER,
    predicted_shares                 INTEGER,
    baseline_likes                   INTEGER,
    baseline_comments                INTEGER,
    baseline_shares                  INTEGER,
    baseline_total_engagement        INTEGER,
    prediction_method                TEXT,
    neighbor_count                   INTEGER,

    status                  TEXT NOT NULL DEFAULT 'scheduled',
    validation_due_at       TIMESTAMPTZ NOT NULL,
    validated_at            TIMESTAMPTZ,

    actual_likes            INTEGER,
    actual_comments         INTEGER,
    actual_shares           INTEGER,
    actual_total_engagement INTEGER,
    actual_engagement_percentile DOUBLE PRECISION,
    prediction_delta        DOUBLE PRECISION,
    accuracy_score          DOUBLE PRECISION,
    likes_delta             DOUBLE PRECISION,
    comments_delta          DOUBLE PRECISION,
    shares_delta            DOUBLE PRECISION,
    total_engagement_delta  DOUBLE PRECISION,
    validation_error        TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS predictions_linkedin_post_id_idx
    ON predictions (linkedin_post_id);

CREATE INDEX IF NOT EXISTS predictions_status_due_idx
    ON predictions (status, validation_due_at);

CREATE TABLE IF NOT EXISTS prediction_engagement_snapshots (
    snapshot_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id   UUID NOT NULL REFERENCES predictions(prediction_id),
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    likes           INTEGER NOT NULL,
    comments        INTEGER NOT NULL,
    shares          INTEGER NOT NULL,
    total_engagement INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS prediction_snapshots_prediction_id_idx
    ON prediction_engagement_snapshots (prediction_id);

ALTER TABLE predictions ADD COLUMN IF NOT EXISTS predicted_likes INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS predicted_comments INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS predicted_shares INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS likes_delta DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS comments_delta DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS shares_delta DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS total_engagement_delta DOUBLE PRECISION;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS baseline_likes INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS baseline_comments INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS baseline_shares INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS baseline_total_engagement INTEGER;


-- HNSW index for fast approximate nearest-neighbour search (Erdal's T1.5
-- success criterion: sub-15ms search).
--
-- pgvector's `vector` type HNSW/IVFFlat indexes are hard-capped at 2000
-- dimensions (ProgramLimitExceeded past that) - our 3072-dim vectors don't
-- fit. Storing 3072-dim `vector` columns is fine (storage limit is 16,000
-- dims); it's only the *index* that's capped. pgvector's documented
-- workaround for >2000-dim vectors is to index a half-precision cast
-- (`halfvec`, added in pgvector 0.7.0, indexable up to 4000 dims) via an
-- expression index, instead of the full-precision column directly:
CREATE INDEX IF NOT EXISTS posts_embedding_hnsw_idx
    ON posts USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops);
-- Queries must cast both sides to match this expression index, e.g.:
--   SELECT post_id FROM posts
--   ORDER BY embedding::halfvec(3072) <=> $1::halfvec(3072) LIMIT 10;

