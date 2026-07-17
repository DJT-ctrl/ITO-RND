#!/usr/bin/env python3
"""Seed deterministic posts + embeddings for docker-compose integration tests.

Usage (stack must already be up with schema applied):

    DATABASE_URL=postgresql://ito:...@localhost:15432/ito_posts \\
      python scripts/integration-seed.py

Idempotent — uses ``insert_posts`` ON CONFLICT upsert.

Reads ``DATABASE_URL`` from the process environment first (does not let
``load_settings()`` / repo ``.env`` clobber a CI-provided DSN).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.vector_store import insert_posts

FIXTURES = ROOT / "tests" / "integration" / "fixtures"


def _resolve_database_url() -> str:
    # Prefer the process env so CI / ci-integration.sh ports win over .env.
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    from config.settings import load_settings

    return load_settings().database_url


def main() -> int:
    posts_path = FIXTURES / "seed_posts.json"
    vectors_path = FIXTURES / "seed_vectors.npy"
    if not posts_path.is_file() or not vectors_path.is_file():
        print(f"Missing fixtures under {FIXTURES}", file=sys.stderr)
        return 1

    records = json.loads(posts_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    if len(records) != len(vectors):
        print(
            f"Fixture length mismatch: {len(records)} posts vs {len(vectors)} vectors",
            file=sys.stderr,
        )
        return 1

    database_url = _resolve_database_url()
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    conn = psycopg.connect(database_url)
    try:
        register_vector(conn)
        n = insert_posts(conn, records, vectors)
    finally:
        conn.close()

    print(f"Seeded {n} integration posts ({', '.join(r['post_id'] for r in records)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
