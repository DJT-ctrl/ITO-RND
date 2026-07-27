# AWS WAF — post-launch edge protections (issue #17)

Regional **WAFv2 Web ACL** for API traffic: AWS managed rule groups, per-IP
rate limit, IP allow/block exception sets, and optional association to an
**Application Load Balancer**.

> AWS WAF cannot attach directly to the Nginx-on-EC2 path from **#14**.
> Post-launch ingress must be **ALB** (or CloudFront with CLOUDFRONT scope).
> This root uses `scope = REGIONAL` for ALB.

## Staged rollout (false-positive validation)

| Phase | `enable_blocking` | Behaviour |
| ----- | ----------------- | --------- |
| 1 — Observe | `false` (default) | Managed + rate rules in **COUNT**; traffic allowed |
| 2 — Enforce | `true` | Rules **Block**; allowlist/blocklist still apply |

`SizeRestrictions_BODY` stays on **Count** even when blocking (API JSON bodies).

## Apply

```bash
cd infra/waf
cp terraform.tfvars.example terraform.tfvars
# set alb_arn when the production ALB exists
terraform init
terraform plan
terraform apply
```

Associate later without recreating the ACL:

```bash
terraform apply -var="alb_arn=arn:aws:elasticloadbalancing:eu-west-2:123:loadbalancer/app/ito-prod/abc"
```

Flip to enforce:

```bash
terraform apply -var="enable_blocking=true" -var="alb_arn=..."
```

## Managed rules (baseline)

| Rule | Purpose |
| ---- | ------- |
| AmazonIpReputationList | Known bad IPs |
| CommonRuleSet | OWASP-ish baseline (XSS, etc.) |
| KnownBadInputsRuleSet | Log4j / bad inputs |
| SQLiRuleSet | SQL injection |
| RateLimitPerIp | Bot / abuse rate control |

## Cost note

ALB + WAF add monthly spend — track against **#18** budgets before enforcing in
`prod`. Prefer `staging` COUNT mode first.

## Acceptance mapping (#17)

| Criterion | Deliverable |
| --------- | ----------- |
| WAF deployed and attached to production ingress | `aws_wafv2_web_acl` + association when `alb_arn` set |
| Baseline managed rules enabled and tuned | Managed groups + rate limit + COUNT→BLOCK flag |
| Runbook includes block/allow exception process | [`docs/ops/WAF.md`](../../docs/ops/WAF.md) |
