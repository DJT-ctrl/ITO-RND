# Ingress hardening artifacts (issue #14)

| File | Purpose |
| ---- | ------- |
| [`sg_allowlist.json`](sg_allowlist.json) | Machine-readable SG + TLS policy (tested in CI) |
| [`../observability/`](../observability/) | CloudWatch (#16) — separate |
| Compose host SG Terraform | Lives in **#12** `infra/terraform/security.tf` |

Runbook: [`docs/ops/INGRESS_HTTPS.md`](../../docs/ops/INGRESS_HTTPS.md).

```bash
python scripts/test_ingress_hardening.py --simulate
pytest tests/test_ingress_https.py -q
```
