# Edge — Web Traffic & Security Guard

The public entry point for the ITO stack: a **free Cloudflare proxy** in front
of an **Nginx origin** that terminates TLS, locks itself to Cloudflare, and
reverse-proxies to the FastAPI service. This is the layer that makes the domain
live over HTTPS and keeps everything behind it safe.

```
                     TLS #1 (Universal SSL,          TLS #2 (origin cert,
                      free, auto-renewed)             Full-strict validated)
   ┌─────────┐  HTTPS   ┌──────────────────┐  HTTPS   ┌───────────────┐  HTTP  ┌──────────┐
   │ Browser │ ───────▶ │ Cloudflare edge   │ ───────▶ │ Nginx (origin)│ ─────▶ │ FastAPI  │
   └─────────┘          │ WAF · DDoS · cache│          │ this repo     │ :8000  │ api:8000 │
                        └──────────────────┘          └───────────────┘        └──────────┘
                                 ▲                              ▲
                       browsers hit Cloudflare,       only Cloudflare IPs may
                       never the origin directly      connect (origin lockdown)
```

Telemetry (Prometheus/Grafana/cAdvisor/node-exporter) is **deliberately not
exposed here** — it stays bound to `127.0.0.1` on the box and is reached over an
SSH tunnel. `/metrics` is additionally hard-blocked at the edge.

## What's in here

```
nginx/
  nginx.conf                        main config: real-IP, CF lockdown, rate-limit
                                    zones, gzip, logging, TLS defaults
  templates/ito.conf.template       server blocks (:80 redirect+ACME, :443 proxy);
                                    rendered by the nginx image's envsubst step
  snippets/
    cloudflare-realip.conf          GENERATED — set_real_ip_from <CF ranges>
    cloudflare-allowlist.conf       GENERATED — geo lockdown ($from_cloudflare)
    security-headers.conf           HSTS + hardening headers
    proxy-backend.conf              shared proxy_set_header / timeouts
cloudflare/
  cloudflare-setup.sh               idempotent CF API: proxied DNS + SSL mode +
                                    Always-HTTPS + HSTS
  update-cloudflare-ips.sh          refresh the two GENERATED snippets from CF
certbot/
  issue-cert.sh                     Let's Encrypt DNS-01 via Cloudflare (auto)
  gen-selfsigned.sh                 self-signed bootstrap / local-test cert
docker-compose.edge.yml             overlay adding the nginx + certbot services
tests/                              self-contained test suite (see Testing)
```

## Prerequisites

- A domain whose nameservers point at Cloudflare (free plan is enough).
- The origin box (the EC2 instance) reachable on a public IP, running the base
  stack (`docker compose up -d` — see [../README.md](../README.md)).
- From the Cloudflare dashboard: the **Zone ID** (zone overview) and a scoped
  **API token** with `Zone:DNS:Edit` + `Zone:Zone Settings:Edit` (+ `Zone:Read`).
  Use a scoped token, never the Global API Key.

Fill these into the repo-root `.env` (keys documented in `.env.example`):

```
CF_API_TOKEN=…            # scoped token
CF_ZONE_ID=…              # zone id
EDGE_DOMAIN=api.example.com
ORIGIN_IP=203.0.113.10    # the origin's public IPv4 (EC2 elastic IP)
LETSENCRYPT_EMAIL=ops@example.com
```

## Deploy (end to end)

```bash
set -a; source .env; set +a          # export the .env vars for the scripts

# 1. Configure the Cloudflare proxy: proxied DNS record + Full(strict) SSL +
#    Always Use HTTPS + HSTS. Idempotent — safe to re-run.
deploy/edge/cloudflare/cloudflare-setup.sh

# 2. Refresh the Cloudflare IP snippets to the current published ranges.
deploy/edge/cloudflare/update-cloudflare-ips.sh

# 3. Get an origin certificate (pick ONE — see "Origin certificate" below):
#    a) Let's Encrypt via Cloudflare DNS-01 (automated validation + renewal):
docker compose -f docker-compose.yml -f deploy/edge/docker-compose.edge.yml \
  run --rm certbot
#    b) …or a self-signed bootstrap just to bring the edge up first:
deploy/edge/certbot/gen-selfsigned.sh

# 4. Bring up the edge (adds nginx :80/:443 in front of the api service and
#    rebinds api to localhost so the ONLY public path is through Nginx).
docker compose -f docker-compose.yml -f deploy/edge/docker-compose.edge.yml up -d

# 5. Lock the origin firewall / EC2 security group: allow inbound 80/443 ONLY
#    from Cloudflare's IP ranges (https://www.cloudflare.com/ips/), plus your
#    SSH IP on 22. This is the network-level twin of the Nginx origin lockdown.
```

Verify:

```bash
curl -sS https://api.example.com/health          # {"status":"ok"} via Cloudflare
curl -sSI http://api.example.com/ | grep -i location   # 301 → https
```

### The two TLS hops (why Full **strict**)

- **Browser → Cloudflare** uses Cloudflare's free Universal SSL cert, issued
  and renewed automatically once the domain is proxied. Nothing to do.
- **Cloudflare → origin** uses the origin cert from step 3. `cloudflare-setup.sh`
  sets the SSL mode to **Full (strict)**, so Cloudflare *validates* that origin
  cert. This closes the two classic holes: "Flexible" (plaintext CF→origin) and
  "Full" (encrypted but unvalidated, so spoofable). Strict needs a cert with a
  real chain — a Let's Encrypt cert **or** a Cloudflare Origin CA cert — not the
  self-signed bootstrap (use "Full" temporarily if you must run self-signed).

### Origin certificate — two supported paths

1. **Let's Encrypt, DNS-01 via Cloudflare (default, `certbot/issue-cert.sh`).**
   Proves domain control by creating a TXT record through the Cloudflare API, so
   it works even though the hostname is proxied and the origin is locked to
   Cloudflare-only. Fully automated issuance **and** renewal. This is the
   "automated HTTPS validation" in the Definition of Done.

2. **Cloudflare Origin CA cert (zero-renewal alternative).** In the dashboard:
   *SSL/TLS → Origin Server → Create Certificate* (15-year validity). Save the
   cert as `deploy/edge/certs/fullchain.pem` and the key as
   `deploy/edge/certs/privkey.pem`, then `docker exec ito-edge nginx -s reload`.
   Only trusted by Cloudflare (perfect for a locked-down origin), no ACME, no
   renewal cron.

### Automated renewal (Let's Encrypt path)

Re-running the `certbot` service is renew-if-due and idempotent (`issue-cert.sh`
calls `certbot certonly`, which no-ops when the cert isn't near expiry and
re-issues + re-publishes when it is). Install a systemd timer (or cron) on the
origin that runs it and reloads Nginx:

```ini
# /etc/systemd/system/ito-cert-renew.service
[Service]
Type=oneshot
WorkingDirectory=/opt/ito-rnd
ExecStart=/usr/bin/docker compose -f docker-compose.yml \
  -f deploy/edge/docker-compose.edge.yml run --rm certbot
ExecStartPost=/usr/bin/docker exec ito-edge nginx -s reload
```
```ini
# /etc/systemd/system/ito-cert-renew.timer
[Timer]
OnCalendar=*-*-* 03:27:00
RandomizedDelaySec=1h
Persistent=true
[Install]
WantedBy=timers.target
```
```bash
sudo systemctl enable --now ito-cert-renew.timer
```

Also refresh the Cloudflare IP snippets monthly (ranges change rarely but do):

```
# crontab
0 4 1 * *  cd /opt/ito-rnd && deploy/edge/cloudflare/update-cloudflare-ips.sh --reload
```

## Security model (defense in depth)

| Layer | Control | Guards against |
| ----- | ------- | -------------- |
| Cloudflare edge | WAF, DDoS mitigation, TLS termination, Always-HTTPS, HSTS | volumetric attacks, plaintext, bots |
| DNS / firewall | origin security group allows 80/443 from CF ranges only | direct-to-origin scanning |
| Nginx `geo` lockdown | `$from_cloudflare` on the real TCP peer → 403 | CF bypass if the origin IP leaks |
| Nginx realip | true client IP from `CF-Connecting-IP` | blind rate-limits / bad logs |
| Nginx rate limits | per-real-IP zones (tight on `/evaluate`) | brute force, cost-draining abuse |
| Nginx | `/metrics` blocked, telemetry never public | metrics/data leakage |
| Nginx | HSTS, `X-Frame-Options`, `nosniff`, CSP, `server_tokens off` | XSS/clickjacking/version fingerprinting |
| Nginx | body-size + timeout caps | slow-loris, oversized uploads |

The `geo` lockdown keys on `$realip_remote_addr` — the **actual** TCP peer,
evaluated before the realip module rewrites `$remote_addr`. So spoofing
`CF-Connecting-IP` from a non-Cloudflare source does not get you past it (the
test suite proves this).

## Testing

Everything here is verified without a real domain, Cloudflare account, or the
full app — using Docker + a mock upstream + a mock CF API:

```bash
deploy/edge/tests/run-all.sh
```

- `test-edge.sh` — `nginx -t` on the shipped config, then behavioural asserts:
  routing, HTTP→HTTPS redirect, ACME path, real-IP restoration, origin lockdown
  (incl. spoofed-header bypass attempt), `/metrics` block, security headers,
  rate limiting.
- `test-cloudflare-setup.sh` — runs `cloudflare-setup.sh` against a mock CF API
  and asserts the create + update (idempotent) branches and every zone setting.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| CF **521** (web server down) | origin not up, or firewall blocks CF on 443 |
| CF **522** (timeout) | security group doesn't allow the CF IP ranges |
| CF **525/526** (TLS handshake / invalid cert) | SSL mode is Full(strict) but the origin cert is self-signed/expired — issue a real cert or drop to "Full" |
| Every request **403** at origin | CF IP snippets stale (`update-cloudflare-ips.sh`) or traffic not actually going through Cloudflare (grey-cloud DNS) |
| Real IP shows as a Cloudflare IP in logs | `cloudflare-realip.conf` stale/missing |

## Notes

- This supersedes the old reference-only `deploy/nginx.conf.example`.
- The `certs/` directory is git-ignored (it holds a private key). It's created
  by `gen-selfsigned.sh` / `issue-cert.sh` at deploy time.
- Host Nginx instead of the container is fine too — copy `nginx.conf` +
  `snippets/` into `/etc/nginx/`, render the template (or drop a plain
  `.conf` with the vars filled in) into `conf.d/`, and set `UPSTREAM_API` to
  `127.0.0.1:8000`.
