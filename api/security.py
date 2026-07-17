"""API authentication, tenant authorization, and rate-limit key helpers.

Issue #3 (API hardening). Also covers Issue #9 tenant-safe ``user_id``
boundaries: ``assert_user_id_authorized()`` blocks cross-tenant impersonation,
security tests live in ``tests/test_api_security.py``, and auth events are
audit-logged with ``tenant_id`` / ``user_id`` context (no payload bodies).

Protected routes require a Bearer API key when ``settings.api_auth_enabled``
is true. Each key maps to a tenant and an optional allow-list of ``user_id``
values so callers cannot impersonate another subscriber by passing an
arbitrary ``user_id`` in the request body. Auth defaults off for local dev
(``API_AUTH_ENABLED=false``); no signup/login account system yet — API keys
are the future-facing tenant principal until real accounts land.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import Settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Populated once from Settings at app startup (see configure_api_security).
_key_registry: dict[str, "ApiPrincipal"] = {}
_auth_enabled: bool = False


@dataclass(frozen=True)
class ApiPrincipal:
    """Authenticated caller derived from a Bearer API key."""

    key_fingerprint: str
    tenant_id: str
    # None = service key; any user_id is accepted (logged for audit).
    allowed_user_ids: Optional[frozenset[str]]


def _fingerprint_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]


def parse_api_key_registry(raw_json: str) -> dict[str, ApiPrincipal]:
    """Parse API_KEYS_JSON into a lookup table keyed by the raw Bearer token."""
    if not raw_json.strip():
        return {}

    try:
        payload: dict[str, Any] = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "API_KEYS_JSON is not valid JSON. Expected an object mapping API keys "
            'to {"tenant_id": "...", "allowed_user_ids": ["user-a"]} records.'
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError("API_KEYS_JSON must be a JSON object.")

    registry: dict[str, ApiPrincipal] = {}
    for raw_key, meta in payload.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("API_KEYS_JSON contains an empty API key entry.")
        if not isinstance(meta, dict):
            raise ValueError(f"API_KEYS_JSON entry for key fingerprint "
                             f"{_fingerprint_api_key(raw_key)} must be an object.")

        tenant_id = meta.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError(
                f"API_KEYS_JSON entry for key fingerprint "
                f"{_fingerprint_api_key(raw_key)} is missing tenant_id."
            )

        allowed_raw = meta.get("allowed_user_ids")
        allowed_user_ids: Optional[frozenset[str]]
        if allowed_raw is None:
            allowed_user_ids = frozenset()
        elif allowed_raw == ["*"] or allowed_raw == "*":
            allowed_user_ids = None
        elif isinstance(allowed_raw, list) and all(isinstance(v, str) for v in allowed_raw):
            if "*" in allowed_raw:
                allowed_user_ids = None
            else:
                allowed_user_ids = frozenset(allowed_raw)
        else:
            raise ValueError(
                f"API_KEYS_JSON entry for tenant {tenant_id} has invalid "
                "allowed_user_ids (expected string array or ['*'])."
            )

        registry[raw_key] = ApiPrincipal(
            key_fingerprint=_fingerprint_api_key(raw_key),
            tenant_id=tenant_id.strip(),
            allowed_user_ids=allowed_user_ids,
        )

    return registry


def configure_api_security(settings: Settings) -> None:
    """Load the API key registry from settings. Called once at app startup."""
    global _key_registry, _auth_enabled
    _auth_enabled = settings.api_auth_enabled
    _key_registry = (
        parse_api_key_registry(settings.api_keys_json)
        if settings.api_keys_json.strip()
        else {}
    )

    if _auth_enabled and not _key_registry:
            logger.warning(
                "API_AUTH_ENABLED is true but API_KEYS_JSON is empty — "
                "all protected requests will be rejected until keys are configured."
            )


def authenticate_api_key(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> ApiPrincipal:
    """Validate Bearer credentials and return the authenticated principal."""
    if not _auth_enabled:
        raise RuntimeError("authenticate_api_key called while API auth is disabled")

    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.info("api_auth_rejected reason=missing_or_invalid_scheme")
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Bearer <api-key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if not token:
        logger.info("api_auth_rejected reason=empty_token")
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Bearer <api-key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = _key_registry.get(token)
    if principal is None:
        logger.info("api_auth_rejected reason=unknown_key fingerprint=%s", _fingerprint_api_key(token))
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(
        "api_auth_ok tenant_id=%s key_fingerprint=%s",
        principal.tenant_id,
        principal.key_fingerprint,
    )
    return principal


def require_api_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> Optional[ApiPrincipal]:
    """FastAPI dependency: optional principal when auth is disabled."""
    if not _auth_enabled:
        return None
    return authenticate_api_key(credentials)


def assert_user_id_authorized(principal: Optional[ApiPrincipal], user_id: Optional[str]) -> None:
    """Reject cross-tenant user_id impersonation for tenant-scoped API keys."""
    if principal is None or user_id is None:
        return

    if principal.allowed_user_ids is None:
        logger.info(
            "api_tenant_access tenant_id=%s key_fingerprint=%s user_id=%s scope=service",
            principal.tenant_id,
            principal.key_fingerprint,
            user_id,
        )
        return

    if user_id in principal.allowed_user_ids:
        logger.info(
            "api_tenant_access tenant_id=%s key_fingerprint=%s user_id=%s scope=allowed",
            principal.tenant_id,
            principal.key_fingerprint,
            user_id,
        )
        return

    logger.warning(
        "api_tenant_denied tenant_id=%s key_fingerprint=%s user_id=%s",
        principal.tenant_id,
        principal.key_fingerprint,
        user_id,
    )
    raise HTTPException(
        status_code=403,
        detail="user_id is not authorized for this API key",
    )


def rate_limit_identity(request: Request) -> str:
    """Rate-limit bucket key: per API key when present, else client IP."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return f"key:{_fingerprint_api_key(token)}"
    client = request.client
    if client and client.host:
        return f"ip:{client.host}"
    return "ip:unknown"
