output "sns_topic_arn" {
  value       = aws_sns_topic.critical.arn
  description = "Critical alerts SNS topic ARN."
}

output "sns_topic_name" {
  value       = aws_sns_topic.critical.name
  description = "Critical alerts SNS topic name."
}

output "log_group_names" {
  value       = { for k, g in aws_cloudwatch_log_group.ito : k => g.name }
  description = "CloudWatch log group names (api / host / docker)."
}

output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.ito_mvp.dashboard_name
  description = "CloudWatch dashboard name."
}

output "alarm_names" {
  value = [
    aws_cloudwatch_metric_alarm.host_status_check.alarm_name,
    aws_cloudwatch_metric_alarm.disk_pressure.alarm_name,
    aws_cloudwatch_metric_alarm.api_error_rate.alarm_name,
    aws_cloudwatch_metric_alarm.api_latency_p95.alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx_log_spike.alarm_name,
  ]
  description = "Essential MVP alarm names."
}

output "next_steps" {
  value = <<-EOT
    1. Confirm SNS email/HTTPS subscription if configured.
    2. On the Compose host: sudo bash deploy/cloudwatch/install-agent.sh ${var.environment}
    3. Enable metrics bridge: python scripts/publish_cw_api_metrics.py --loop
    4. Controlled alarm test: python scripts/test_cloudwatch_alarms.py --alarm ${aws_cloudwatch_metric_alarm.api_error_rate.alarm_name}
    5. Open dashboard ${aws_cloudwatch_dashboard.ito_mvp.dashboard_name} in CloudWatch console.
  EOT
}
