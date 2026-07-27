"""Per-key / per-IP rate limiting for the FastAPI app."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from api.security import rate_limit_identity

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=rate_limit_identity)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Log rate-limit hits; delegate response formatting to slowapi defaults."""
    identity = rate_limit_identity(request)
    logger.warning("api_rate_limited identity=%s detail=%s", identity, exc.detail)
    from slowapi import _rate_limit_exceeded_handler

    return _rate_limit_exceeded_handler(request, exc)


def optional_rate_limit(limit: Optional[str]) -> Callable:
    """Apply slowapi limit decorator only when a limit string is configured."""
    def decorator(endpoint):
        if not limit:
            return endpoint
        return limiter.limit(limit)(endpoint)

    return decorator
