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

-- Speeds up tenant-scoped retrieval (WHERE user_id = ...) and the voice-
-- profile aggregation query in storage/vector_store.get_user_voice_profile().
CREATE INDEX IF NOT EXISTS posts_user_id_idx ON posts (user_id) WHERE user_id IS NOT NULL;


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

