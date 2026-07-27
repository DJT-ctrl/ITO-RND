output "sns_topic_arn" {
  value       = aws_sns_topic.budget_alerts.arn
  description = "SNS topic for budget alerts (email / Slack / PagerDuty)."
}

output "budget_names" {
  value = [
    aws_budgets_budget.monthly_overall.name,
    aws_budgets_budget.monthly_ec2.name,
    aws_budgets_budget.monthly_ebs.name,
    aws_budgets_budget.monthly_cloudwatch.name,
  ]
  description = "AWS Budgets names created for the MVP cost guardrails."
}

output "budget_split_usd" {
  value       = local.budget_split
  description = "Documented monthly USD split (overall + service slices)."
}

output "next_steps" {
  value = <<-EOT
    1. Confirm SNS email subscriptions (and HTTPS Slack/PagerDuty if set).
    2. Generate monthly report: python scripts/generate_monthly_cost_report.py --month YYYY-MM
    3. Review report + playbook docs/ops/COST_CONTROLS.md on the first business day of each month.
    4. If forecast alerts fire mid-month, follow the response steps in the playbook.
  EOT
}
