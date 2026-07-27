locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = {
    "ito:project"    = var.project
    "ito:env"        = var.environment
    "ito:managed-by" = "terraform"
    "ito:issue"      = "18"
  }

  # Documented service-level split for the low-cost MVP (sums ≤ overall).
  budget_split = {
    overall    = var.monthly_budget_usd
    ec2        = var.ec2_budget_usd
    ebs        = var.ebs_budget_usd
    cloudwatch = var.cloudwatch_budget_usd
    other      = max(var.monthly_budget_usd - var.ec2_budget_usd - var.ebs_budget_usd - var.cloudwatch_budget_usd, 0)
  }

  subscriber_emails = var.alert_emails
  subscriber_sns    = [aws_sns_topic.budget_alerts.arn]
}
