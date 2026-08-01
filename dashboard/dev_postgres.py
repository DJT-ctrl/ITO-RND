"""One-click local Postgres bootstrap for the Streamlit dev dashboard."""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from config.paths import PROJECT_ROOT
from dotenv import dotenv_values, load_dotenv

_ENV_PATH = PROJECT_ROOT / ".env"
_ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
_COMPOSE_TIMEOUT_START = 300


@dataclass(frozen=True)
class DevPostgresStep:
    key: str
    label: str
    state: Literal["ok", "warn", "error", "pending"]
    detail: str = ""


@dataclass
class DevPostgresStatus:
    ready: bool
    steps: list[DevPostgresStep] = field(default_factory=list)
    database_url: str = ""


@dataclass
class BootstrapResult:
    ok: bool
    message: str
    logs: tuple[str, ...] = ()


def _compose_env() -> dict[str, str]:
    load_dotenv(_ENV_PATH, override=True)
    env = dict(**{k: v for k, v in __import__("os").environ.items() if v is not None})
    for key, value in dotenv_values(_ENV_PATH).items():
        if value is not None:
            env[key] = value
    return env


def _read_env_map() -> dict[str, str]:
    if not _ENV_PATH.exists():
        return {}
    return {k: v for k, v in dotenv_values(_ENV_PATH).items() if v is not None}


def database_url_from_parts(
    *,
    user: str,
    password: str,
    host: str = "localhost",
    port: int = 5432,
    dbname: str,
) -> str:
    safe_password = quote_plus(password)
    return f"postgresql://{user}:{safe_password}@{host}:{port}/{dbname}"


def _sync_database_url_in_file() -> None:
    """Ensure DATABASE_URL matches POSTGRES_* in an existing .env file."""
    if not _ENV_PATH.exists():
        return
    values = _read_env_map()
    user = values.get("POSTGRES_USER", "ito")
    password = values.get("POSTGRES_PASSWORD", "")
    dbname = values.get("POSTGRES_DB", "ito_posts")
    if not password:
        return
    host_port = values.get("DB_HOST_PORT", "5432")
    try:
        port = int(host_port)
    except ValueError:
        port = 5432
    target = database_url_from_parts(
        user=user, password=password, port=port, dbname=dbname
    )
    text = _ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^DATABASE_URL=.*$", text, flags=re.MULTILINE):
        text = re.sub(
            r"^DATABASE_URL=.*$",
            f"DATABASE_URL={target}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        text = text.rstrip() + f"\nDATABASE_URL={target}\n"
    _ENV_PATH.write_text(text, encoding="utf-8")


def ensure_dev_env_file() -> tuple[bool, str]:
    """Create repo-root .env from .env.example when missing (dev-only)."""
    if _ENV_PATH.exists():
        _sync_database_url_in_file()
        return True, "Using existing .env"

    if not _ENV_EXAMPLE.exists():
        return False, ".env.example is missing from the repo."

    password = secrets.token_urlsafe(18)
    shutil.copyfile(_ENV_EXAMPLE, _ENV_PATH)
    text = _ENV_PATH.read_text(encoding="utf-8")
    text = text.replace("change_me_before_use", password)
    _ENV_PATH.write_text(text, encoding="utf-8")
    _sync_database_url_in_file()
    return True, "Created .env from .env.example (generated dev password)."


def docker_cli_available() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except FileNotFoundError:
        return False, "Docker CLI not found — install Docker Desktop."
    except subprocess.TimeoutExpired:
        return False, "Docker CLI timed out."
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return False, f"docker compose unavailable: {err}"
    return True, "Docker Compose ready"


def postgres_connect_ok(*, connect_timeout: int = 2) -> tuple[bool, str]:
    """Cheap reachability check — must not block Streamlit page loads.

    Uses a short TCP connect timeout and only ``SELECT 1`` (no schema migrate).
    """
    load_dotenv(_ENV_PATH, override=True)
    from config.settings import load_settings

    settings = load_settings()
    if not settings.database_url:
        return False, "DATABASE_URL is empty"
    try:
        import psycopg

        # Explicit timeout: a half-open SSH tunnel on :5432 otherwise hangs
        # the whole dashboard sidebar for minutes.
        conn = psycopg.connect(
            settings.database_url,
            connect_timeout=connect_timeout,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:
        return False, str(exc)
    return True, "Connected and schema OK"


def diagnose_dev_postgres() -> DevPostgresStatus:
    steps: list[DevPostgresStep] = []

    if _ENV_PATH.exists():
        steps.append(
            DevPostgresStep("env", ".env file", "ok", str(_ENV_PATH.relative_to(PROJECT_ROOT)))
        )
    else:
        steps.append(
            DevPostgresStep(
                "env",
                ".env file",
                "error",
                "Missing — one-click setup will copy .env.example",
            )
        )

    env_map = _read_env_map()
    database_url = env_map.get("DATABASE_URL", "")
    if database_url:
        steps.append(DevPostgresStep("url", "DATABASE_URL", "ok", "set"))
    else:
        steps.append(
            DevPostgresStep(
                "url",
                "DATABASE_URL",
                "error",
                "Not set — setup will derive from POSTGRES_*",
            )
        )

    docker_ok, docker_detail = docker_cli_available()
    steps.append(
        DevPostgresStep(
            "docker",
            "Docker Compose",
            "ok" if docker_ok else "error",
            docker_detail,
        )
    )

    if database_url:
        conn_ok, conn_detail = postgres_connect_ok()
        steps.append(
            DevPostgresStep(
                "connect",
                "Postgres reachable",
                "ok" if conn_ok else "warn",
                conn_detail,
            )
        )
        ready = conn_ok
    else:
        steps.append(
            DevPostgresStep(
                "connect",
                "Postgres reachable",
                "pending",
                "Start database to check",
            )
        )
        ready = False

    return DevPostgresStatus(ready=ready, steps=steps, database_url=database_url)


def _run_compose(
    *args: str,
    timeout: int = _COMPOSE_TIMEOUT_START,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_compose_env(),
    )


def _wait_for_postgres(timeout: int = 120) -> tuple[bool, str]:
    env_map = _read_env_map()
    user = env_map.get("POSTGRES_USER", "ito")
    dbname = env_map.get("POSTGRES_DB", "ito_posts")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "pg_isready",
                "-U",
                user,
                "-d",
                dbname,
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=_compose_env(),
        )
        if result.returncode == 0:
            return True, "Postgres is accepting connections"
        time.sleep(2)
    return False, "Timed out waiting for Postgres (is Docker Desktop running?)"


def bootstrap_local_postgres() -> BootstrapResult:
    """Create .env if needed, start db + migrate via compose, verify host connection."""
    logs: list[str] = []

    ok, msg = ensure_dev_env_file()
    logs.append(msg)
    if not ok:
        return BootstrapResult(False, msg, tuple(logs))

    load_dotenv(_ENV_PATH, override=True)
    _sync_database_url_in_file()
    load_dotenv(_ENV_PATH, override=True)

    docker_ok, docker_msg = docker_cli_available()
    logs.append(docker_msg)
    if not docker_ok:
        return BootstrapResult(False, docker_msg, tuple(logs))

    env_map = _read_env_map()
    database_url = env_map.get("DATABASE_URL", "")
    if database_url:
        conn_ok, conn_detail = postgres_connect_ok()
        if conn_ok:
            logs.append(conn_detail)
            return BootstrapResult(True, "Postgres already running.", tuple(logs))

    logs.append("Starting docker compose services: db, migrate…")
    up = _run_compose("up", "-d", "db")
    if up.returncode != 0:
        err = (up.stderr or up.stdout or "").strip()
        logs.append(err)
        return BootstrapResult(False, f"Could not start db: {err}", tuple(logs))
    logs.append((up.stdout or "").strip() or "db service started")

    ready, wait_msg = _wait_for_postgres()
    logs.append(wait_msg)
    if not ready:
        return BootstrapResult(False, wait_msg, tuple(logs))

    logs.append("Applying schema (migrate)…")
    migrate = _run_compose("run", "--rm", "migrate")
    if migrate.returncode != 0 and "No such image" in (migrate.stderr or migrate.stdout or ""):
        logs.append("Building api image (first-time setup)…")
        build = _run_compose("build", "api", timeout=600)
        if build.returncode != 0:
            err = (build.stderr or build.stdout or "").strip()
            logs.append(err)
            return BootstrapResult(False, f"Docker build failed: {err}", tuple(logs))
        migrate = _run_compose("run", "--rm", "migrate")
    if migrate.returncode != 0:
        err = (migrate.stderr or migrate.stdout or "").strip()
        logs.append(err)
        return BootstrapResult(False, f"Schema migrate failed: {err}", tuple(logs))
    logs.append((migrate.stdout or "").strip() or "schema ready")

    load_dotenv(_ENV_PATH, override=True)
    conn_ok, conn_detail = postgres_connect_ok()
    logs.append(conn_detail)
    if not conn_ok:
        return BootstrapResult(False, conn_detail, tuple(logs))

    return BootstrapResult(True, "Local Postgres is ready.", tuple(logs))
