"""Tests for processors/gemini_retry.py."""

from unittest.mock import patch

import pytest
from google.genai import errors as genai_errors

from processors.gemini_retry import (
    call_with_gemini_retry,
    gemini_error_code,
    is_retryable_gemini_error,
)


def test_gemini_error_code_reads_api_error_code():
    exc = genai_errors.APIError(503, {"error": {"message": "high demand"}})
    assert gemini_error_code(exc) == 503


def test_is_retryable_gemini_error_for_503():
    exc = genai_errors.APIError(503, {"error": {"message": "high demand"}})
    assert is_retryable_gemini_error(exc) is True


def test_is_retryable_gemini_error_rejects_400():
    exc = genai_errors.APIError(400, {"error": {"message": "bad request"}})
    assert is_retryable_gemini_error(exc) is False


def test_call_with_gemini_retry_retries_503_then_succeeds():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        if calls["count"] == 1:
            raise genai_errors.APIError(
                503,
                {"error": {"message": "high demand", "status": "UNAVAILABLE"}},
            )
        return "ok"

    with patch("processors.gemini_retry.time.sleep") as mock_sleep:
        assert call_with_gemini_retry(fn, max_attempts=3) == "ok"

    assert calls["count"] == 2
    mock_sleep.assert_called_once()


def test_call_with_gemini_retry_raises_after_max_attempts():
    def fn():
        raise genai_errors.APIError(503, {"error": {"message": "high demand"}})

    with patch("processors.gemini_retry.time.sleep"):
        with pytest.raises(genai_errors.APIError):
            call_with_gemini_retry(fn, max_attempts=2)
