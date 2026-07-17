output "web_acl_arn" {
  value       = aws_wafv2_web_acl.api.arn
  description = "WAFv2 Web ACL ARN."
}

output "web_acl_id" {
  value       = aws_wafv2_web_acl.api.id
  description = "WAFv2 Web ACL id."
}

output "web_acl_name" {
  value       = aws_wafv2_web_acl.api.name
  description = "WAFv2 Web ACL name."
}

output "associated_alb_arn" {
  value       = var.alb_arn
  description = "ALB ARN associated (empty if not attached yet)."
}

output "blocking_enabled" {
  value       = var.enable_blocking
  description = "Whether managed/rate rules enforce Block (false = COUNT staged mode)."
}

output "next_steps" {
  value = <<-EOT
    1. Put an ALB (or CloudFront) in front of the Compose host — WAF cannot attach to bare EC2/Nginx (#14).
    2. terraform apply -var="alb_arn=arn:aws:elasticloadbalancing:..." -var="enable_blocking=false"
    3. Watch sampled requests / metrics for false positives (staging first).
    4. Flip enable_blocking=true after review. Exception process: docs/ops/WAF.md
  EOT
}
