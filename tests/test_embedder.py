"""Unit tests for processors/embedder.py (T1.3: Vector Embedding Generation)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from google.genai import errors as genai_errors

from config.settings import Settings
from processors.embedder import embed_batch, embed_query, save_embeddings


def make_settings(**overrides) -> Settings:
    defaults = dict(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="test-gemini-key",
        raw_data_dir="data/raw",
        default_search_limit=10,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_record(post_id: str, content: str, word_count: int) -> dict:
    return {"post_id": post_id, "content": content, "word_count": word_count}


def fake_embed_response(n: int, dim: int = 3072):
    """Build a MagicMock shaped like an EmbedContentResponse for n posts."""
    response = MagicMock()
    response.embeddings = [MagicMock(values=[0.1] * dim) for _ in range(n)]
    response.usage_metadata = MagicMock(prompt_token_count=42)
    return response


LONG_TEXT = "word " * 12  # word_count >= 10


# ── embed_batch: filtering ──────────────────────────────────────────────────

def test_embed_batch_raises_without_api_key():
    records = [make_record("1", LONG_TEXT, 12)]
    with pytest.raises(ValueError):
        embed_batch(records, make_settings(gemini_api_key=""))


def test_embed_batch_skips_short_word_count():
    records = [make_record("1", "too short", 2)]
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(0)
        vectors, skipped = embed_batch(records, make_settings())
    assert vectors.shape == (0, 3072)
    assert skipped == 1


def test_embed_batch_skips_blank_content():
    records = [make_record("1", "   ", 12)]
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(0)
        vectors, skipped = embed_batch(records, make_settings())
    assert vectors.shape == (0, 3072)
    assert skipped == 1


def test_embed_batch_returns_vectors_for_valid_records():
    records = [make_record("1", LONG_TEXT, 12), make_record("2", LONG_TEXT, 15)]
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(2)
        vectors, skipped = embed_batch(records, make_settings())
    assert vectors.shape == (2, 3072)
    assert skipped == 0


def test_embed_batch_mixed_valid_and_skipped():
    records = [make_record("1", LONG_TEXT, 12), make_record("2", "short", 1)]
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(1)
        vectors, skipped = embed_batch(records, make_settings())
    assert vectors.shape == (1, 3072)
    assert skipped == 1


# ── embed_batch: retries ────────────────────────────────────────────────────

def test_embed_batch_retries_on_rate_limit_then_succeeds():
    records = [make_record("1", LONG_TEXT, 12)]
    rate_limit_error = genai_errors.APIError(429, {"error": {"message": "rate limited"}})

    with patch("processors.embedder.genai.Client") as mock_client_cls, patch("time.sleep") as mock_sleep:
        mock_client_cls.return_value.models.embed_content.side_effect = [
            rate_limit_error,
            fake_embed_response(1),
        ]
        vectors, skipped = embed_batch(records, make_settings())

    assert vectors.shape == (1, 3072)
    assert mock_sleep.call_count == 1


def test_embed_batch_raises_after_max_attempts():
    records = [make_record("1", LONG_TEXT, 12)]
    server_error = genai_errors.APIError(500, {"error": {"message": "server error"}})

    with patch("processors.embedder.genai.Client") as mock_client_cls, patch("time.sleep"):
        mock_client_cls.return_value.models.embed_content.side_effect = server_error
        with pytest.raises(genai_errors.APIError):
            embed_batch(records, make_settings())


def test_embed_batch_does_not_retry_on_client_error():
    records = [make_record("1", LONG_TEXT, 12)]
    bad_request_error = genai_errors.APIError(400, {"error": {"message": "bad request"}})

    with patch("processors.embedder.genai.Client") as mock_client_cls, patch("time.sleep") as mock_sleep:
        mock_client_cls.return_value.models.embed_content.side_effect = bad_request_error
        with pytest.raises(genai_errors.APIError):
            embed_batch(records, make_settings())
    mock_sleep.assert_not_called()


# ── save_embeddings ──────────────────────────────────────────────────────────

def test_save_embeddings_writes_npy_file(tmp_path):
    vectors = np.zeros((3, 3072), dtype=np.float32)
    out_path = save_embeddings(vectors, "linkedin", base_dir=str(tmp_path))

    assert out_path.exists()
    assert out_path.name.startswith("linkedin_gemini_")
    assert out_path.suffix == ".npy"

    loaded = np.load(out_path)
    assert loaded.shape == (3, 3072)


# ── embed_query ──────────────────────────────────────────────────────────

def test_embed_query_raises_without_api_key():
    with pytest.raises(ValueError):
        embed_query("some draft text", make_settings(gemini_api_key=""))


def test_embed_query_uses_retrieval_query_task_type():
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(1)
        embed_query("some draft text", make_settings())

    call_kwargs = mock_client_cls.return_value.models.embed_content.call_args.kwargs
    assert call_kwargs["config"].task_type == "RETRIEVAL_QUERY"
    assert call_kwargs["contents"] == ["some draft text"]


def test_embed_query_returns_1d_vector_and_token_count():
    with patch("processors.embedder.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.models.embed_content.return_value = fake_embed_response(1)
        vector, prompt_tokens = embed_query("some draft text", make_settings())

    assert vector.shape == (3072,)
    assert prompt_tokens == 42
