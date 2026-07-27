# AWS ingress hardening — HTTPS + strict security groups (MVP)

Issue **#14** — TLS termination, HTTP redirect/block, and documented security
group posture for the Compose-on-EC2 MVP (`budget:low-cost-mvp`).

| Choice | MVP decision |
| ------ | ------------ |
| Edge path | **Nginx on the Compose host** (not ALB) — avoids ~$16+/mo ALB fee inside the #18 budget envelope |
| Certificates | **Let's Encrypt via Certbot** (HTTP-01). Optional ACM+ALB path documented below for later |
| WAF | **Deferred to [#17](https://github.com/intotheopen/intotheopen-backend/issues/17)** — evaluated, not enabled on MVP (title: defer WAF) |

Prerequisites: host from **#12**, deploy path **#20**, prefer secrets **#13**.

---

## Target architecture

```
Internet
   │
   ├─ TCP 443 ──► Nginx (TLS) ──► 127.0.0.1:8000 (API)
   └─ TCP 80  ──► Nginx 301 → https://$host$request_uri
```

- API / Grafana / Prometheus **must not** be published on `0.0.0.0` for production.
- Compose already binds Postgres and telemetry to localhost; keep **API behind Nginx only** on the public interface.
- Security group: allow **80** (redirect) + **443** from `allowed_cidrs`; **no** public `8000` / `5432` / `3000` / `9090`.

Machine-readable allowlist: [`infra/ingress/sg_allowlist.json`](../../infra/ingress/sg_allowlist.json).

---

## Security group rules (documented + tested)

| Direction | Port | Source | Purpose |
| --------- | ---- | ------ | ------- |
| Inbound | **443/tcp** | `allowed_cidrs` (prefer app/frontend IPs, not `0.0.0.0/0` in prod) | HTTPS API |
| Inbound | **80/tcp** | same | ACME HTTP-01 + redirect to HTTPS |
| Inbound | **22/tcp** | optional `ssh_cidrs` only | Prefer **SSM** instead |
| Inbound | **8000, 5432, 3000, 9090, …** | **none (public)** | Forbidden |
| Outbound | all | `0.0.0.0/0` | Packages, Secrets Manager, S3, providers |

Terraform for the Compose host SG ships with **#12** (`infra/terraform/security.tf`).
This issue **locks the policy** and verifies it via
`scripts/test_ingress_hardening.py` / `tests/test_ingress_https.py`.

After #12 apply, confirm:

```bash
aws ec2 describe-security-groups --group-ids <sg-id> \
  --query 'SecurityGroups[0].IpPermissions'
# Expect tcp 80 + 443 (+ optional 22). No 8000/5432.
```

---

## HTTPS-only API (Nginx + Certbot)

### 1. DNS

Point an A/AAAA record (e.g. `api.example.com`) at the instance Elastic IP (#12).

### 2. Install Nginx + config

```bash
sudo dnf install -y nginx certbot python3-certbot-nginx   # AL2023
sudo cp deploy/nginx/ito-api.conf /etc/nginx/conf.d/ito-api.conf
# edit server_name to your hostname
sudo nginx -t && sudo systemctl enable --now nginx
```

Template: [`deploy/nginx/ito-api.conf`](../../deploy/nginx/ito-api.conf)
(HTTP → HTTPS redirect + TLS reverse proxy to `127.0.0.1:8000`).

### 3. Issue certificate

```bash
sudo bash deploy/nginx/install-tls.sh api.example.com you@example.com
```

Or manually:

```bash
sudo certbot --nginx -d api.example.com --agree-tos -m you@example.com --redirect
```

### 4. Verify acceptance

```bash
# HTTPS works
curl -sfI https://api.example.com/health

# HTTP redirects (301/302) or is blocked — not a cleartext API
curl -sI http://api.example.com/health | head -5
# Expect: HTTP/1.1 301 Moved Permanently  Location: https://...

# Direct API port must not be world-reachable (from your laptop):
curl -sf --connect-timeout 3 http://<public-ip>:8000/health && echo 'FAIL: 8000 open' || echo 'OK: 8000 closed'
```

Offline / CI checks:

```bash
python scripts/test_ingress_hardening.py --simulate
pytest tests/test_ingress_https.py -q
```

---

## Optional later path: ACM + ALB

Use when budget allows and you want AWS-managed TLS at the load balancer:

1. Request ACM cert in the same region as the ALB (DNS validation).
2. ALB listener **443** → target group → instance **:80** (Nginx) or **:8000** (only from ALB SG).
3. ALB listener **80** → redirect to 443.
4. Instance SG: allow **80** only from the ALB security group (drop public 80/443 on instance if ALB terminates TLS).

Not the default for MVP because of ALB cost vs `#18` monthly envelope.

---

## WAF evaluation (deferred)

| Option | MVP decision | Why |
| ------ | ------------ | --- |
| AWS WAF on ALB / CloudFront | **Defer → #17** | Needs ALB/CloudFront; managed rule groups add cost/complexity before launch |
| Nginx rate limits / request size | Optional light hardening in `ito-api.conf` | Cheap baseline, not a substitute for WAF |
| Security groups | **In scope for #14** | Primary edge control for single-instance MVP |

**Documented outcome:** WAF baseline managed rules are **evaluated and deferred**
until post-launch issue **#17**. Security group + HTTPS redirect rules are
**in scope and tested** here.

---

## Acceptance mapping (#14)

| Criterion | Deliverable |
| --------- | ----------- |
| API reachable only over HTTPS | Nginx TLS `server` + API on `127.0.0.1:8000` |
| HTTP redirected or blocked | `return 301 https://…` on port 80 |
| WAF and SG rules documented and tested | This doc (WAF → #17) + `sg_allowlist.json` + hardening tests |
