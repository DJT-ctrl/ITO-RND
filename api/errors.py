"""API error taxonomy and exception-to-envelope mapping (issue #7)."""

from __future__ import annotations

from typing import Any, Optional

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.genai import errors as genai_errors

from api.schemas import ApiErrorResponse
from processors.gemini_retry import gemini_error_code, is_retryable_gemini_error


class ApiError(Exception):
    """Raised by handlers or mapped from lower-level failures."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        retryable: bool,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details
        super().__init__(message)

    def to_response(self) -> ApiErrorResponse:
        return ApiErrorResponse(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )


def map_exception(exc: BaseException) -> ApiError:
    """Map a known backend failure to a stable API error envelope."""
    if isinstance(exc, ApiError):
        return exc

    if isinstance(exc, HTTPException):
        return _map_http_exception(exc)

    if isinstance(exc, genai_errors.APIError):
        provider_status = gemini_error_code(exc)
        retryable = is_retryable_gemini_error(exc)
        if provider_status is not None and 400 <= provider_status < 600:
            status_code = provider_status
        else:
            status_code = 503
        return ApiError(
            code="PROVIDER_ERROR",
            message="AI provider request failed.",
            status_code=status_code,
            retryable=retryable,
            details={"provider": "google", "provider_status": provider_status},
        )

    if isinstance(exc, psycopg.Error):
        return ApiError(
            code="DATABASE_UNAVAILABLE",
            message="Database is temporarily unavailable.",
            status_code=503,
            retryable=True,
            details={"error_type": type(exc).__name__},
        )

    if isinstance(exc, ValueError):
        return _map_value_error(exc)

    return ApiError(
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
        status_code=500,
        retryable=True,
        details=None,
    )


def _map_value_error(exc: ValueError) -> ApiError:
    message = str(exc)
    lowered = message.lower()
    if "gemini_api_key" in lowered or "api key" in lowered:
        return ApiError(
            code="CONFIG_MISSING",
            message="Required AI provider configuration is missing.",
            status_code=503,
            retryable=False,
            details={"config_key": "GEMINI_API_KEY"},
        )
    if "embed" in lowered:
        return ApiError(
            code="EMBED_FAILED",
            message=message,
            status_code=500,
            retryable=True,
            details={"provider": "google"},
        )
    return ApiError(
        code="BAD_REQUEST",
        message=message,
        status_code=400,
        retryable=False,
    )


def _map_http_exception(exc: HTTPException) -> ApiError:
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message", "retryable"} <= detail.keys():
        return ApiError(
            code=str(detail["code"]),
            message=str(detail["message"]),
            status_code=exc.status_code,
            retryable=bool(detail["retryable"]),
            details=detail.get("details"),
        )

    message = str(detail)
    retryable = exc.status_code in {408, 429, 500, 502, 503, 504}
    code_by_status = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        408: "REQUEST_TIMEOUT",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "PROVIDER_ERROR",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    return ApiError(
        code=code_by_status.get(exc.status_code, "INTERNAL_ERROR"),
        message=message,
        status_code=exc.status_code,
        retryable=retryable,
        details=None,
    )


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return _json_error(exc)


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return _json_error(map_exception(exc))


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    return _json_error(map_exception(exc))


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Keep FastAPI's 422 validation shape — documented as ValidationErrorResponse in #6.
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def _json_error(error: ApiError) -> JSONResponse:
    payload = error.to_response().model_dump()
    return JSONResponse(status_code=error.status_code, content=payload)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
