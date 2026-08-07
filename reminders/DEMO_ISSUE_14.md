# Demo — Issue #14 (HTTPS ingress)

**Branch:** `feature/issue-14-https-ingress`  
**Issue:** [intotheopen/intotheopen-backend#14](https://github.com/intotheopen/intotheopen-backend/issues/14)

| Criterion | Deliverable |
| --------- | ----------- |
| HTTPS-only API | `deploy/nginx/ito-api.conf` + Certbot install script |
| HTTP redirect | `return 301 https://…` |
| SG + WAF documented/tested | `sg_allowlist.json` + `INGRESS_HTTPS.md` (WAF → #17) |

```bash
pytest tests/test_ingress_https.py -q
python scripts/test_ingress_hardening.py --simulate
```
