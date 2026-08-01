"""Tests for dev Postgres bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from dashboard.dev_postgres import database_url_from_parts, ensure_dev_env_file


def test_database_url_from_parts_encodes_password() -> None:
    url = database_url_from_parts(
        user="ito",
        password="p@ss:w/rd",
        dbname="ito_posts",
    )
    assert url.startswith("postgresql://ito:")
    assert "@localhost:5432/ito_posts" in url


def test_ensure_dev_env_creates_from_example(tmp_path: Path, monkeypatch) -> None:
    example = tmp_path / ".env.example"
    example.write_text(
        "POSTGRES_USER=ito\n"
        "POSTGRES_PASSWORD=change_me_before_use\n"
        "POSTGRES_DB=ito_posts\n"
        "DATABASE_URL=postgresql://ito:change_me_before_use@localhost:5432/ito_posts\n",
        encoding="utf-8",
    )
    target = tmp_path / ".env"
    monkeypatch.setattr("dashboard.dev_postgres._ENV_PATH", target)
    monkeypatch.setattr("dashboard.dev_postgres._ENV_EXAMPLE", example)

    ok, msg = ensure_dev_env_file()
    assert ok is True
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "change_me_before_use" not in text
    assert "DATABASE_URL=postgresql://" in text
