"""Invite-only gate for the demo deployment.

Shows a password screen first. After a correct password, the existing Streamlit
harness runs unchanged (same navigation and pages as local).

Auth is kept in session state for the current visit, and mirrored to a cookie so
Vercel container restarts do not bounce the viewer back to the password screen.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

_SESSION_KEY = "ito_invite_authenticated"
_COOKIE_NAME = "ito_invite_auth"


def invite_configured() -> bool:
    """True when this deployment expects an invite password."""
    if (os.getenv("DEMO_INVITE_PASSWORD") or os.getenv("INVITE_PASSWORD") or "").strip():
        return True
    if (os.getenv("DEMO_INVITE_USE_FIREBASE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    try:
        secrets = st.secrets  # type: ignore[attr-defined]
        if str(secrets.get("DEMO_INVITE_PASSWORD", "") or "").strip():
            return True
        if str(secrets.get("INVITE_PASSWORD", "") or "").strip():
            return True
    except Exception:
        pass
    return False


def _expected_password() -> Optional[str]:
    for key in ("DEMO_INVITE_PASSWORD", "INVITE_PASSWORD"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    try:
        secrets = st.secrets  # type: ignore[attr-defined]
        for key in ("DEMO_INVITE_PASSWORD", "INVITE_PASSWORD"):
            value = str(secrets.get(key, "") or "").strip()
            if value:
                return value
    except Exception:
        pass
    if (os.getenv("DEMO_INVITE_USE_FIREBASE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return _password_from_firestore()
    return None


def _password_from_firestore() -> Optional[str]:
    """Read invite password from Firestore when Firebase is configured."""
    project_id = (os.getenv("FIREBASE_PROJECT_ID") or "").strip()
    if not project_id:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        logger.warning("firebase-admin not installed; skipping Firestore invite lookup")
        return None

    try:
        if not firebase_admin._apps:
            cred_json = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
            if cred_json:
                import json

                cred = credentials.Certificate(json.loads(cred_json))
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                firebase_admin.initialize_app(options={"projectId": project_id})
        db = firestore.client()
        snap = db.collection("demo_invites").document("shared").get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        password = str(data.get("password") or "").strip()
        return password or None
    except Exception:
        logger.exception("Firestore invite lookup failed")
        return None


def _auth_token(expected_password: str) -> str:
    return hmac.new(
        expected_password.encode("utf-8"),
        b"ito-invite-v1",
        hashlib.sha256,
    ).hexdigest()


def _passwords_match(provided: str, expected: str) -> bool:
    left = hashlib.sha256(provided.encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


def _cookie_token() -> Optional[str]:
    try:
        cookies = getattr(st.context, "cookies", None)
        if cookies is None:
            return None
        value = cookies.get(_COOKIE_NAME)
        return str(value) if value else None
    except Exception:
        return None


def _set_auth_cookie(token: str) -> None:
    # Mirror auth to a first-party cookie so Fluid/container restarts keep access.
    components.html(
        f"""
        <script>
        document.cookie = "{_COOKIE_NAME}={token}; path=/; max-age=604800; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )


def _hide_app_chrome() -> None:
    st.markdown(
        """
        <style>
        #MainMenu, header, footer, [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stHeader"],
        [data-testid="stDecoration"] { display: none !important; visibility: hidden !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _is_authenticated(expected: str) -> bool:
    if st.session_state.get(_SESSION_KEY):
        return True
    cookie = _cookie_token()
    if cookie and hmac.compare_digest(cookie, _auth_token(expected)):
        st.session_state[_SESSION_KEY] = True
        return True
    return False


def require_invite() -> bool:
    """Block until invite password is accepted; then return and let the normal app run."""
    expected = _expected_password()
    if not expected:
        _hide_app_chrome()
        st.title("Invite only")
        st.error(
            "This demo is not configured yet (missing DEMO_INVITE_PASSWORD "
            "or Firestore invite). Ask the host for a fresh link."
        )
        st.stop()
        return False

    if _is_authenticated(expected):
        return True

    # Password-only screen — no harness navigation until unlocked.
    _hide_app_chrome()
    st.title("Invite only")
    st.write("Enter the shared password to open the test harness.")

    with st.form("invite_gate", clear_on_submit=False):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Continue", type="primary")

    if submitted:
        if _passwords_match(password.strip(), expected):
            token = _auth_token(expected)
            st.session_state[_SESSION_KEY] = True
            _set_auth_cookie(token)
            st.rerun()
        st.error("Incorrect password.")

    st.stop()
    return False
