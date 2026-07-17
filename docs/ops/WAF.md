# AWS WAF & edge protections (post-launch)

Issue **#17** — enable AWS WAF after launch with managed rules, rate controls,
staged COUNT→BLOCK rollout, and an exception (allow/block) process.

Related: MVP HTTPS without WAF is **#14**. Cost envelope **#18**.

## Why ALB (or CloudFront) is required

AWS WAF associates with ALB, CloudFront, API Gateway, etc. — **not** with a
bare EC2/Nginx listener. Post-launch production ingress for WAF:

```
Internet → WAF → ALB :443 → target (Compose host :80 Nginx or :8000)
```

CloudFront alternative: recreate the Web ACL with `scope = CLOUDFRONT` in
`us-east-1` (not covered by this regional Terraform root).

---

## Deploy & attach

```bash
cd infra/waf
cp terraform.tfvars.example terraform.tfvars
# staging first
terraform apply -var="environment=staging" -var="enable_blocking=false"
# when ALB exists:
terraform apply -var="alb_arn=<alb-arn>" -var="enable_blocking=false"
```

Verify association:

```bash
aws wafv2 list-resources-for-web-acl \
  --web-acl-arn <web-acl-arn> \
  --resource-type APPLICATION_LOAD_BALANCER
```

Offline checks:

```bash
python scripts/test_waf_edge.py --simulate
pytest tests/test_aws_waf.py -q
```

---

## Baseline managed rules (tuned for API)

| Priority | Rule | Notes |
| -------- | ---- | ----- |
| 0 | IpAllowlist | Optional break-glass CIDRs — **Allow** |
| 1 | IpBlocklist | Optional abuse CIDRs — **Block** |
| 10 | AmazonIpReputationList | Managed |
| 20 | CommonRuleSet | `SizeRestrictions_BODY` forced **Count** (JSON bodies) |
| 30 | KnownBadInputsRuleSet | Managed |
| 40 | SQLiRuleSet | Managed |
| 50 | RateLimitPerIp | Default 2000 req / 5 min / IP |

Default Web ACL action: **Allow** (only explicit rules block when enforcing).

---

## Staged rollout (false-positive validation)

1. **COUNT mode** (`enable_blocking = false`) on **staging** for ≥ 48h.
2. Review WAF sampled requests + CloudWatch metrics for false positives on
   `/api/v1/similar-posts` and `/api/v1/evaluate`.
3. Add allowlist CIDRs or rule overrides for known-good clients (Lovable preview
   IPs, uptime checks).
4. Promote COUNT to **staging** with `enable_blocking = true` for a soak.
5. Repeat on **prod**: COUNT → review → BLOCK.
6. Record the flip date in the monthly cost/security notes (#18 / #27).

---

## Block / allow exception process

### Allow an IP/CIDR (false positive or office break-glass)

1. Confirm the client is legitimate (owner approval).
2. Add CIDR to `ip_allowlist` in `terraform.tfvars`.
3. `terraform apply` (rule **IpAllowlist** priority 0).
4. Comment on the incident / issue: who, why, expiry date if temporary.
5. Re-test the previously blocked request.
6. Remove temporary allowlist entries within **14 days** unless permanent.

### Block an IP/CIDR (abuse)

1. Capture evidence (WAF sample, logs, rate spike).
2. Add CIDR to `ip_blocklist`.
3. `terraform apply`.
4. Notify on-call channel; link CloudWatch/WAF console.
5. Review weekly; remove when abuse stops.

### Disable / bypass a managed rule (last resort)

1. Prefer Count override for a single rule name inside the managed group
   (see `SizeRestrictions_BODY` pattern in `infra/waf/waf.tf`).
2. Document the override in this runbook’s change log section (below).
3. Never set Web ACL `default_action` to Block without an allowlist.

### Emergency: detach WAF from ALB

```bash
# Remove association by clearing alb_arn or terraform destroy -target association
terraform apply -var="alb_arn="
# or AWS console: WAF → Web ACL → Associated AWS resources → Disassociate
```

HTTPS on origin (#14 Nginx) should still work; you lose edge filtering only.

---

## Change log (overrides)

| Date | Change | Owner |
| ---- | ------ | ----- |
| _tmpl_ | e.g. Count override for RuleX | _name_ |

---

## Acceptance mapping

| Criterion | Where |
| --------- | ----- |
| WAF deployed and attached | `infra/waf` + `alb_arn` association |
| Baseline managed rules enabled and tuned | `waf.tf` + staged `enable_blocking` |
| Block/allow exception process | This runbook |
