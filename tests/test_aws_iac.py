"""Validate Terraform IaC layout for issue #12."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra"
TF = INFRA / "terraform"
ENVS = INFRA / "envs"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "terraform.yml"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"

REQUIRED_TF = [
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "locals.tf",
    "network.tf",
    "security.tf",
    "iam.tf",
    "compute.tf",
    "storage.tf",
    "outputs.tf",
]


def test_terraform_files_exist():
    assert (INFRA / "README.md").is_file()
    for name in REQUIRED_TF:
        assert (TF / name).is_file(), name


def test_env_tfvars_examples_cover_dev_staging_prod():
    for env in ("dev", "staging", "prod"):
        path = ENVS / f"{env}.tfvars.example"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert f'environment' in text and f'"{env}"' in text


def test_infra_readme_has_bootstrap_and_teardown():
    text = (INFRA / "README.md").read_text(encoding="utf-8")
    assert "Bootstrap" in text
    assert "Teardown" in text
    assert "terraform apply" in text
    assert "terraform destroy" in text
    assert "Drift" in text or "drift" in text


def test_security_group_does_not_expose_postgres():
    text = (TF / "security.tf").read_text(encoding="utf-8")
    assert "5432" not in text
    assert "443" in text
    assert "ssh" in text.lower()


def test_iam_least_privilege_mentions_secrets_and_ssm():
    text = (TF / "iam.tf").read_text(encoding="utf-8")
    assert "secretsmanager:GetSecretValue" in text
    assert "AmazonSSMManagedInstanceCore" in text


def test_ebs_volume_tagged_for_postgres_data():
    text = (TF / "storage.tf").read_text(encoding="utf-8")
    assert 'ito:role" = "postgres-data"' in text or '"ito:role" = "postgres-data"' in text


def test_imdsv2_required_on_instance():
    text = (TF / "compute.tf").read_text(encoding="utf-8")
    assert 'http_tokens                 = "required"' in text or 'http_tokens = "required"' in text


def test_ci_workflow_has_fmt_validate_and_plan_drift():
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "terraform fmt" in text
    assert "terraform validate" in text
    assert "detailed-exitcode" in text
    assert "drift" in text.lower()


def test_issue_backlog_documents_issue_12():
    assert BACKLOG.is_file()
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #12 — requirements" in text
    assert "IaC" in text or "Terraform" in text
