# AWS-managed secrets and credential rotation

Issue **#13** — production secrets live in **AWS Secrets Manager**, are injected
at runtime (never baked into images or durable server `.env` files), and are
rotated with a documented playbook.

Local development still uses a gitignored repo-root `.env` (from `.env.example`).

## Architecture

```
AWS Secrets Manager (JSON secret, e.g. ito/prod/runtime)
        │
        │  GetSecretValue (EC2 instance role)
        ▼
scripts/fetch_aws_secrets.py  →  /run/ito/runtime.env  (tmpfs, mode 0600)
        │
        │  ITO_ENV_FILE=/run/ito/runtime.env
        ▼
docker compose  →  container env  →  config.settings.load_settings()
```

Optional in-process path: set `ITO_AWS_SECRET_ID` (or `ITO_AWS_SECRET_ARN`) in
the process environment; `load_settings()` calls
`config.aws_secrets.load_aws_secrets_into_environ()` before reading knobs.
Prefer the **fetch script + Compose env_file** path on EC2 so Postgres /
Grafana also receive passwords without embedding them in the unit file.

Images already exclude `.env` (see `.dockerignore`). Do not `COPY` secrets.

## Secret payload

Create one JSON secret (example shape: [`secrets.example.json`](secrets.example.json)):

| Key | Required in prod |
| --- | ---------------- |
| `GEMINI_API_KEY` | yes |
| `APIFY_API_TOKEN` | yes |
| `POSTGRES_PASSWORD` | yes |
| `GRAFANA_ADMIN_PASSWORD` | yes |
| `LINKEDIN_COOKIES` | optional (empty OK) |
| `API_KEYS_JSON` | when API auth (#3) is enabled |
| `POSTGRES_USER` / `POSTGRES_DB` | recommended companions |

Name suggestion: `ito/prod/runtime` (or account-specific ARN).

### IAM (instance profile)

Minimum:

```json
{
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue"],
  "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:ito/prod/runtime*"
}
```

Provision the role with IaC when **#12** lands; until then attach manually on
the MVP EC2 instance.

## EC2 / systemd wiring

1. Install AWS CLI **or** project venv with `boto3` on the host.
2. Set in `/etc/ito/ito.env` (root-owned, `0600`) — **non-secret** pointers only:

```bash
ITO_AWS_SECRET_ID=ito/prod/runtime
AWS_REGION=eu-west-2
ITO_ENV_FILE=/run/ito/runtime.env
```

3. Use the updated [`ito-stack.service`](ito-stack.service): `ExecStartPre` runs
   `fetch_aws_secrets.py`, then Compose uses `ITO_ENV_FILE`.
4. Confirm there is **no** long-lived `/opt/ito-rnd/.env` with production
   credentials on the instance.

Manual fetch:

```bash
sudo mkdir -p /run/ito
sudo ITO_AWS_SECRET_ID=ito/prod/runtime AWS_REGION=eu-west-2 \
  /opt/ito-rnd/.venv/bin/python /opt/ito-rnd/scripts/fetch_aws_secrets.py \
  --out /run/ito/runtime.env --require-production-keys
sudo systemctl restart ito-stack
```

## Rotation policy

| Credential | Cadence | How to rotate |
| ---------- | ------- | ------------- |
| `GEMINI_API_KEY` | ≤ 90 days, or on exposure | Issue new Google AI Studio key → update secret JSON → fetch → restart stack |
| `APIFY_API_TOKEN` | ≤ 90 days, or on exposure | Apify console → new token → update secret → fetch → restart |
| `LINKEDIN_COOKIES` | on exposure / session invalid | Re-export Cookie-Editor JSON → update secret → fetch → restart |
| `POSTGRES_PASSWORD` | ≤ 90 days | See coordinated DB steps below |
| `GRAFANA_ADMIN_PASSWORD` | ≤ 90 days | Update secret + Grafana admin password (or recreate Grafana volume) → restart |
| `API_KEYS_JSON` | on user offboarding / exposure | Update secret → fetch → restart API |

### Coordinated Postgres password rotation

1. `ALTER USER ito WITH PASSWORD 'new-password';` against the running DB
   (localhost / SG-restricted).
2. Update `POSTGRES_PASSWORD` (and `DATABASE_URL` if stored) in Secrets Manager.
3. Re-run `fetch_aws_secrets.py` and `systemctl restart ito-stack`.
4. Verify: `curl -s localhost:8000/health` and a `similar-posts` smoke call.

Never rotate the DB password in Secrets Manager **without** step 1 first — the
API will fail to connect.

### After any rotation

- Confirm `/run/ito/runtime.env` mtime updated and mode `0600`.
- Confirm journal: `journalctl -u ito-stack -n 50`.
- Confirm no plain-text secret leftovers under `/opt/ito-rnd/.env`.

## Playbook dry-run (tested in CI)

Automated coverage of the rotation flow (no AWS account required):

```bash
pytest tests/test_aws_secrets.py -q
```

That suite:

1. Loads `deploy/secrets.example.json`
2. Writes a temp runtime env file
3. Simulates rotating `GEMINI_API_KEY` / `POSTGRES_PASSWORD`
4. Re-writes the env file and asserts new values

### One-time live AWS verification (ops checklist)

Run once per environment before go-live (#27):

- [ ] Secret created in Secrets Manager (JSON matches example keys)
- [ ] Instance role can `GetSecretValue`
- [ ] `fetch_aws_secrets.py --require-production-keys` succeeds on the host
- [ ] Stack starts with `ITO_ENV_FILE=/run/ito/runtime.env` and **no** prod `.env`
- [ ] Rotate `GEMINI_API_KEY` in SM → fetch → restart → `/health` still OK
- [ ] Tick this checklist in the deploy notes for #20 / #27

## Acceptance mapping (#13)

| Criterion | How |
| --------- | --- |
| No production secrets in repo or server-side `.env` | Example JSON placeholders only; prod uses `/run/ito/runtime.env` from SM |
| App reads secrets from managed AWS secret store | Fetch → Compose env / optional `load_aws_secrets_into_environ` |
| Rotation playbook tested end-to-end | `tests/test_aws_secrets.py` dry-run + live checklist above |
