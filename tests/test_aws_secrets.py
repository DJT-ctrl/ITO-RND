"""Tests for AWS Secrets Manager integration and rotation dry-run (issue #13)."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.aws_secrets import (
    AwsSecretsError,
    apply_secrets_to_environ,
    fetch_secret_dict,
    missing_production_secrets,
    parse_secret_string,
    secret_dict_to_env_lines,
    simulate_rotation,
    write_env_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_JSON = REPO_ROOT / "deploy" / "secrets.example.json"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_aws_secrets.py"
SECRETS_DOC = REPO_ROOT / "deploy" / "SECRETS.md"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"


def test_secrets_docs_and_example_exist():
    assert SECRETS_DOC.is_file()
    text = SECRETS_DOC.read_text(encoding="utf-8")
    assert "Secrets Manager" in text
    assert "Rotation policy" in text
    assert "Playbook dry-run" in text
    assert EXAMPLE_JSON.is_file()
    assert FETCH_SCRIPT.is_file()


def test_issue_backlog_documents_issue_13():
    assert BACKLOG.is_file()
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #13 — requirements" in text
    assert "Secrets Manager" in text or "secret store" in text.lower()


def test_parse_secret_string_and_missing_keys():
    secrets = parse_secret_string(EXAMPLE_JSON.read_text(encoding="utf-8"))
    assert secrets["GEMINI_API_KEY"] == "replace-me-gemini"
    # Example uses placeholders — still counts as present.
    assert missing_production_secrets(secrets) == []
    assert missing_production_secrets({"GEMINI_API_KEY": ""}) == [
        "GEMINI_API_KEY",
        "APIFY_API_TOKEN",
        "POSTGRES_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
    ]


def test_fetch_secret_dict_uses_injected_client():
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"GEMINI_API_KEY": "from-aws", "POSTGRES_PASSWORD": "db"})
    }
    secrets = fetch_secret_dict("ito/prod/runtime", client=client)
    assert secrets["GEMINI_API_KEY"] == "from-aws"
    client.get_secret_value.assert_called_once_with(SecretId="ito/prod/runtime")


def test_fetch_secret_dict_raises_on_aws_failure():
    client = MagicMock()
    client.get_secret_value.side_effect = RuntimeError("AccessDenied")
    with pytest.raises(AwsSecretsError, match="GetSecretValue failed"):
        fetch_secret_dict("ito/prod/runtime", client=client)


def test_write_env_file_is_private(tmp_path):
    path = tmp_path / "runtime.env"
    write_env_file({"GEMINI_API_KEY": "abc", "NOTE": "hello world"}, path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    text = path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=abc" in text
    assert 'NOTE="hello world"' in text


def test_apply_secrets_to_environ_override():
    environ = {"GEMINI_API_KEY": "old"}
    applied = apply_secrets_to_environ({"GEMINI_API_KEY": "new"}, environ, override=True)
    assert environ["GEMINI_API_KEY"] == "new"
    assert applied == ["GEMINI_API_KEY"]


def test_rotation_playbook_dry_run_end_to_end(tmp_path):
    """Simulate rotate → rewrite env file → verify new values (issue #13 AC)."""
    v1 = parse_secret_string(EXAMPLE_JSON.read_text(encoding="utf-8"))
    out1 = tmp_path / "runtime-v1.env"
    write_env_file(v1, out1)
    assert "replace-me-gemini" in out1.read_text(encoding="utf-8")

    v2 = simulate_rotation(
        v1,
        {
            "GEMINI_API_KEY": "rotated-gemini-key",
            "POSTGRES_PASSWORD": "rotated-postgres-password",
        },
    )
    assert v2["GEMINI_API_KEY"] == "rotated-gemini-key"
    assert v2["POSTGRES_PASSWORD"] == "rotated-postgres-password"
    assert missing_production_secrets(v2) == []

    out2 = tmp_path / "runtime-v2.env"
    write_env_file(v2, out2)
    text = out2.read_text(encoding="utf-8")
    assert "rotated-gemini-key" in text
    assert "rotated-postgres-password" in text
    assert "replace-me-gemini" not in text


def test_fetch_script_from_json_dry_run(tmp_path):
    out = tmp_path / "runtime.env"
    completed = subprocess.run(
        [
            sys.executable,
            str(FETCH_SCRIPT),
            "--from-json",
            str(EXAMPLE_JSON),
            "--out",
            str(out),
            "--require-production-keys",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert out.is_file()
    assert "GEMINI_API_KEY=" in out.read_text(encoding="utf-8")


def test_compose_and_gitignore_mention_runtime_env():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ITO_ENV_FILE" in compose
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "runtime.env" in gitignore
    unit = (REPO_ROOT / "deploy" / "ito-stack.service").read_text(encoding="utf-8")
    assert "compose-with-runtime-env.sh" in unit
    wrapper = (REPO_ROOT / "deploy" / "compose-with-runtime-env.sh").read_text(encoding="utf-8")
    assert "--env-file" in wrapper


def test_secret_dict_to_env_lines_stable_order():
    lines = secret_dict_to_env_lines({"B": "2", "A": "1"})
    assert lines.index("A=1") < lines.index("B=2")
