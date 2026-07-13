"""Shared retry helpers for transient Google Gemini / Google GLA API errors."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, Optional, TypeVar

from google.genai import errors as genai_errors

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_S = 2.0
DEFAULT_MAX_DELAY_S = 60.0

T = TypeVar("T")


def gemini_error_code(exc: BaseException) -> Optional[int]:
    if isinstance(exc, genai_errors.APIError):
        return exc.code
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return int(status_code)
    return None


def is_retryable_gemini_error(exc: BaseException) -> bool:
    code = gemini_error_code(exc)
    if code is None:
        return False
    return code in RETRYABLE_STATUS_CODES


def _retry_delay_s(
    attempt: int,
    *,
    base_delay_s: float,
    max_delay_s: float,
) -> float:
    delay = min(base_delay_s * (2**attempt), max_delay_s)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def call_with_gemini_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    label: str = "Gemini call",
) -> T:
    """Run a sync Gemini call, retrying transient HTTP errors with backoff."""
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not is_retryable_gemini_error(exc) or attempt >= max_attempts - 1:
                raise
            delay_s = _retry_delay_s(
                attempt,
                base_delay_s=base_delay_s,
                max_delay_s=max_delay_s,
            )
            logger.warning(
                "%s transient error (%s) — retrying in %.1fs (attempt %s/%s)",
                label,
                gemini_error_code(exc),
                delay_s,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{label} failed without an error")


async def async_call_with_gemini_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    label: str = "Gemini call",
) -> T:
    """Run an async Gemini call, retrying transient HTTP errors with backoff."""
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if not is_retryable_gemini_error(exc) or attempt >= max_attempts - 1:
                raise
            delay_s = _retry_delay_s(
                attempt,
                base_delay_s=base_delay_s,
                max_delay_s=max_delay_s,
            )
            logger.warning(
                "%s transient error (%s) — retrying in %.1fs (attempt %s/%s)",
                label,
                gemini_error_code(exc),
                delay_s,
                attempt + 1,
                max_attempts,
            )
            await asyncio.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"{label} failed without an error")
