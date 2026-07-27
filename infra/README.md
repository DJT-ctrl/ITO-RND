# AWS infrastructure (Terraform) — issue #12

Minimal **single-EC2 Docker Compose** VPC for IntoTheOpen, matching
ADR-001 / issue [#11](https://github.com/intotheopen/intotheopen-backend/issues/11)
(`docs/ops/ADR-001-aws-runtime.md` when merged).

This directory provisions:

| Resource | Purpose |
| -------- | ------- |
| VPC + public subnet + IGW + routes | MVP network (single AZ) |
| Security groups | HTTPS/HTTP (+ optional SSH); deny public Postgres |
| IAM role + instance profile | SSM, Secrets Manager read, S3 backup |
| EC2 instance | Compose host |
| EBS data volume | Postgres `DB_DATA_PATH` (`ito:role=postgres-data`) |
| Optional Elastic IP | Stable public address |

Environment separation: **`dev` / `staging` / `prod`** via `*.tfvars` + distinct state keys.

## Prerequisites

- Terraform `>= 1.5`
- AWS credentials with rights to create VPC/EC2/IAM/EBS (admin or scoped bootstrap role)
- Optional remote state bucket (recommended for shared envs)

## Bootstrap (fresh environment from code only)

### 1. One-time remote state (recommended)

```bash
# Example — adjust region/name
aws s3api create-bucket \
  --bucket ito-terraform-state-<ACCOUNT_ID> \
  --region eu-west-2 \
  --create-bucket-configuration LocationConstraint=eu-west-2
aws s3api put-bucket-versioning \
  --bucket ito-terraform-state-<ACCOUNT_ID> \
  --versioning-configuration Status=Enabled
```

```bash
cd infra/terraform
cp backend.tf.example backend.tf          # gitignored
cp backend.hcl.example backend.hcl        # gitignored — edit bucket/key/region
```

First-time solo apply may skip remote state and use local `.terraform/` state
(fine for a personal sandbox; use S3 state for shared envs).

### 2. Choose environment

```bash
cd infra/terraform
cp ../envs/dev.tfvars.example ../envs/dev.tfvars
# edit: key_name (optional), allowed_cidrs, secret ARN prefix, backup bucket name
```

### 3. Init / plan / apply

```bash
cd infra/terraform
# Local state (sandbox):
terraform init
# Or remote state:
#   cp backend.tf.example backend.tf && terraform init -backend-config=backend.hcl

terraform plan  -var-file=../envs/dev.tfvars -out=tfplan
terraform apply tfplan
```

Outputs include instance id, public IP/DNS, security group ids, and IAM role name.

### 4. Host follow-ups (not Terraform)

After apply, on the instance (SSM Session Manager preferred):

1. Install Docker + Compose, clone repo to `/opt/ito-rnd` (#20 runbook).
2. Attach/mount the data volume at `DB_DATA_PATH` if not already in user-data.
3. Wire Secrets Manager → runtime env (#13).
4. `systemctl enable --now ito-stack`.

## Teardown

```bash
cd infra/terraform
terraform destroy -var-file=../envs/dev.tfvars
```

**Before destroy:** confirm backups (#15) — destroy deletes the EBS volume unless
`prevent_destroy` lifecycle is enabled on prod (see `enable_volume_protection`).

Remove empty state bucket only when no environments remain.

## Plan / apply workflow

| Step | Command |
| ---- | ------- |
| Format | `terraform fmt -recursive infra/terraform` |
| Validate | `terraform init -backend=false && terraform validate` |
| Plan | `terraform plan -var-file=../envs/<env>.tfvars` |
| Apply | `terraform apply -var-file=../envs/<env>.tfvars` |

**CI drift detection:** `.github/workflows/terraform.yml` runs `fmt` + `validate`
on every PR, and `terraform plan -detailed-exitcode` when AWS OIDC/credentials
are configured (exit code `2` = drift / pending changes → fails the job).

## Tagging standard

All resources receive:

| Tag | Example |
| --- | ------- |
| `ito:project` | `intotheopen` |
| `ito:env` | `dev` / `staging` / `prod` |
| `ito:managed-by` | `terraform` |
| `ito:issue` | `12` |
| `ito:role` | e.g. `compose-host`, `postgres-data` |

## Least privilege (defaults)

- Instance role: `secretsmanager:GetSecretValue` on `secret_arn_prefix*`,
  `s3:PutObject`/`GetObject`/`ListBucket` on backup bucket, SSM core.
- SG: no public `5432`; SSH optional and CIDR-restricted; HTTP(S) from `allowed_cidrs`.

## Acceptance mapping (#12)

| Criterion | Deliverable |
| --------- | ----------- |
| Fresh env from code only | This README bootstrap + `terraform apply` |
| Drift detection in CI/CD | `.github/workflows/terraform.yml` plan exit code |
| Bootstrap and teardown docs | This README |
