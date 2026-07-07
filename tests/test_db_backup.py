"""Unit tests for storage/db_backup.py.

Mocks subprocess.run throughout — repo convention is no real docker/DB
calls in unit tests (see storage/vector_store.py's tests for the same
pattern with psycopg). _parse_dsn is pure and gets exercised directly with
no mocking needed.
"""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from storage.db_backup import _parse_dsn, create_backup, list_backups, restore_backup


def make_settings(database_url: str = "postgresql://ito:secret@localhost:5432/ito_posts") -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="",
        raw_data_dir="data/raw",
        default_search_limit=10,
        database_url=database_url,
    )


# ── _parse_dsn ───────────────────────────────────────────────────────────────

def test_parse_dsn_extracts_user_and_dbname():
    assert _parse_dsn("postgresql://ito:secret@localhost:5432/ito_posts") == ("ito", "ito_posts")


def test_parse_dsn_handles_no_port():
    assert _parse_dsn("postgresql://someuser@db/somedb") == ("someuser", "somedb")


def test_parse_dsn_raises_on_empty_url():
    with pytest.raises(ValueError):
        _parse_dsn("")


def test_parse_dsn_raises_when_dbname_missing():
    with pytest.raises(ValueError):
        _parse_dsn("postgresql://ito:secret@localhost:5432/")


# ── create_backup ────────────────────────────────────────────────────────────

def test_create_backup_invokes_docker_compose_pg_dump(tmp_path):
    settings = make_settings()
    fake_result = MagicMock(returncode=0, stderr=b"")

    with patch("storage.db_backup.subprocess.run", return_value=fake_result) as mock_run:
        backup_path = create_backup(settings, backup_dir=str(tmp_path))

    assert backup_path.parent == tmp_path
    assert backup_path.name.startswith("posts_pre_ingest_")
    assert backup_path.name.endswith(".dump")

    command = mock_run.call_args.args[0]
    assert command[:5] == ["docker", "compose", "exec", "-T", "db"]
    assert "pg_dump" in command
    assert "-U" in command and "ito" in command
    assert "-d" in command and "ito_posts" in command


def test_create_backup_raises_and_removes_partial_file_on_failure(tmp_path):
    settings = make_settings()
    fake_result = MagicMock(returncode=1, stderr=b"connection refused")

    with patch("storage.db_backup.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError):
            create_backup(settings, backup_dir=str(tmp_path))

    # No leftover partial dump file after a failed pg_dump.
    assert list(tmp_path.glob("posts_pre_ingest_*.dump")) == []


# ── restore_backup ───────────────────────────────────────────────────────────

def test_restore_backup_invokes_docker_compose_pg_restore(tmp_path):
    settings = make_settings()
    dump_file = tmp_path / "posts_pre_ingest_20260101T000000Z.dump"
    dump_file.write_bytes(b"fake-dump-contents")
    fake_result = MagicMock(returncode=0, stderr=b"")

    with patch("storage.db_backup.subprocess.run", return_value=fake_result) as mock_run:
        restore_backup(settings, dump_file)

    command = mock_run.call_args.args[0]
    assert command[:5] == ["docker", "compose", "exec", "-T", "db"]
    assert "pg_restore" in command
    assert "--clean" in command
    assert "--if-exists" in command


def test_restore_backup_raises_on_missing_file(tmp_path):
    settings = make_settings()
    with pytest.raises(FileNotFoundError):
        restore_backup(settings, tmp_path / "does_not_exist.dump")


def test_restore_backup_raises_on_pg_restore_failure(tmp_path):
    settings = make_settings()
    dump_file = tmp_path / "posts_pre_ingest_20260101T000000Z.dump"
    dump_file.write_bytes(b"fake-dump-contents")
    fake_result = MagicMock(returncode=1, stderr=b"restore failed")

    with patch("storage.db_backup.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError):
            restore_backup(settings, dump_file)


# ── list_backups ─────────────────────────────────────────────────────────────

def test_list_backups_returns_empty_list_when_dir_missing(tmp_path):
    assert list_backups(str(tmp_path / "missing")) == []


def test_list_backups_returns_sorted_dump_files(tmp_path):
    (tmp_path / "posts_pre_ingest_20260102T000000Z.dump").write_bytes(b"")
    (tmp_path / "posts_pre_ingest_20260101T000000Z.dump").write_bytes(b"")
    (tmp_path / "not_a_backup.txt").write_bytes(b"")

    backups = list_backups(str(tmp_path))
    assert [b.name for b in backups] == [
        "posts_pre_ingest_20260101T000000Z.dump",
        "posts_pre_ingest_20260102T000000Z.dump",
    ]
