"""Batch-embeds LinkedIn post text into 3072-dimension vectors (T1.3).

Erdal's spec: "Run a single batched Python script processing raw texts
through OpenAI (?) embedding endpoint. Handle retries locally. 100% of
posts mapped to 3072-dimension floating-point arrays with no broken text
strings."

Model choice — gemini-embedding-001, NOT text-embedding-004
--------------------------------------------------------------
`models/text-embedding-004` is fixed at 768 dimensions — it cannot produce
the 3072-dim vectors Erdal's spec requires. `models/gemini-embedding-001`
supports `output_dimensionality=3072` (its native size, so no truncation
quality loss) and — critically — embeds each string in a `contents` list
independently, which is what per-post batching needs. (A newer
`gemini-embedding-2` model exists but *aggregates* a whole `contents=[...]`
list into one embedding unless each input is wrapped in its own `Content`
object, which is the wrong shape for "one embedding per post".)

Two functions:
  embed_batch()     — text -> vectors, with local retry handling.
  save_embeddings()  — vectors -> timestamped .npy file on disk.

A third function, embed_query(), embeds a single query string at request
time for T2's similarity-search endpoint (see below for why it needs its
own task_type rather than reusing embed_batch()).
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from config.settings import Settings

_MODEL = "models/gemini-embedding-001"
_OUTPUT_DIMENSIONALITY = 3072
_BATCH_SIZE = 100
_MAX_ATTEMPTS = 3
_MIN_WORD_COUNT = 10


def embed_batch(records: list[dict[str, Any]], settings: Settings) -> tuple[np.ndarray, int]:
    """Embed each record's `content` field into a 3072-dim vector.

    Records with `word_count < 10` or blank/missing `content` are skipped
    (empty/near-empty text produces low-signal, unreliable embeddings) —
    this is how the "no broken text strings" requirement is satisfied.

    Returns:
        (vectors, skipped_count)
        vectors: shape (n_valid_posts, 3072), in the same order as the
                 valid (non-skipped) subset of ``records``.
        skipped_count: how many posts were excluded.

    Raises:
        ValueError: if settings.gemini_api_key is not set.
        google.genai.errors.APIError: if a batch still fails after retries.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set (check your .env file).")

    valid = [
        record
        for record in records
        if (record.get("content") or "").strip() and record.get("word_count", 0) >= _MIN_WORD_COUNT
    ]
    skipped = len(records) - len(valid)
    if not valid:
        return np.empty((0, _OUTPUT_DIMENSIONALITY), dtype=np.float32), skipped

    client = genai.Client(api_key=settings.gemini_api_key)
    contents = [record["content"] for record in valid]

    all_vectors: list[list[float]] = []
    for start in range(0, len(contents), _BATCH_SIZE):
        batch = contents[start : start + _BATCH_SIZE]
        all_vectors.extend(_embed_with_retry(client, batch))

    vectors = np.array(all_vectors, dtype=np.float32)
    return vectors, skipped


def embed_query(text: str, settings: Settings) -> np.ndarray:
    """Embed a single query string for similarity search against stored posts.

    Uses task_type="RETRIEVAL_QUERY" (not "RETRIEVAL_DOCUMENT", which
    embed_batch() uses for stored posts) — Gemini's asymmetric retrieval
    mode expects queries and documents embedded with matching-but-different
    task types for best retrieval accuracy. Reuses the same retry logic
    (_embed_with_retry) as embed_batch(), just with a single-element batch.

    Returns:
        A 1-D array of shape (3072,).

    Raises:
        ValueError: if settings.gemini_api_key is not set.
        google.genai.errors.APIError: if the request still fails after retries.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set (check your .env file).")

    client = genai.Client(api_key=settings.gemini_api_key)
    vectors = _embed_with_retry(client, [text], task_type="RETRIEVAL_QUERY")
    return np.array(vectors[0], dtype=np.float32)


def _embed_with_retry(client: "genai.Client", batch: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Call the embedding endpoint for one batch, retrying transient errors.

    Retries on HTTP 429 (rate limit) and 5xx (server error) with
    exponential backoff (1s, 2s, 4s), up to 3 attempts total. Any other
    error (e.g. 4xx bad input) is not retryable and raises immediately.
    """
    delay = 1.0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = client.models.embed_content(
                model=_MODEL,
                contents=batch,
                config=genai_types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=_OUTPUT_DIMENSIONALITY,
                ),
            )
            return [embedding.values for embedding in response.embeddings]
        except genai_errors.APIError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if not retryable or attempt == _MAX_ATTEMPTS:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")  # loop always returns or raises


def save_embeddings(vectors: np.ndarray, platform: str, base_dir: str = "data/embeddings") -> Path:
    """Persist embedding vectors to a timestamped .npy file, return its path.

    Output filename: <platform>_gemini_<timestamp>.npy
    Example: linkedin_gemini_20260704T210000Z.npy

    The .npy file holds only the raw vectors (no post_id/content) — pair
    vector[i] with its source post by re-deriving the same valid subset
    (word_count >= 10, non-blank content) used by embed_batch().
    """
    out_dir = Path(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_path = out_dir / f"{platform}_gemini_{timestamp}.npy"
    np.save(file_path, vectors)
    return file_path
