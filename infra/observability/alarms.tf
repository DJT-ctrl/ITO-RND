# Host health — AWS/EC2 status checks (no agent required).
resource "aws_cloudwatch_metric_alarm" "host_status_check" {
  alarm_name          = "${local.name_prefix}-host-status-check-failed"
  alarm_description   = "EC2 instance status check failed. See docs/ops/CLOUDWATCH.md#host-status-check-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "breaching"

  dimensions = {
    InstanceId = var.compose_host_instance_id
  }

  alarm_actions = [aws_sns_topic.critical.arn]
  ok_actions    = [aws_sns_topic.critical.arn]

  tags = {
    "ito:role"     = "alarm"
    "ito:severity" = "critical"
  }
}

# Disk pressure — requires CloudWatch agent (CWAgent namespace).
resource "aws_cloudwatch_metric_alarm" "disk_pressure" {
  alarm_name          = "${local.name_prefix}-disk-used-percent"
  alarm_description   = "Root disk used percent high. See docs/ops/CLOUDWATCH.md#disk-used-percent"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "disk_used_percent"
  namespace           = "CWAgent"
  period              = 60
  statistic           = "Average"
  threshold           = var.disk_used_percent_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = var.compose_host_instance_id
    path       = "/"
    fstype     = "xfs"
  }

  alarm_actions = [aws_sns_topic.critical.arn]
  ok_actions    = [aws_sns_topic.critical.arn]

  tags = {
    "ito:role"     = "alarm"
    "ito:severity" = "critical"
  }
}

# API error rate — published by scripts/publish_cw_api_metrics.py (ITO/API).
resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${local.name_prefix}-api-error-rate"
  alarm_description   = "API 5xx error rate elevated. See docs/ops/CLOUDWATCH.md#api-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ErrorRate"
  namespace           = local.metric_namespace
  period              = 300
  statistic           = "Average"
  threshold           = var.api_error_rate_threshold
  treat_missing_data  = "notBreaching"
  unit                = "Percent"

  dimensions = {
    Environment = var.environment
  }

  alarm_actions = [aws_sns_topic.critical.arn]
  ok_actions    = [aws_sns_topic.critical.arn]

  tags = {
    "ito:role"     = "alarm"
    "ito:severity" = "critical"
  }
}

# API latency p95 — published by scripts/publish_cw_api_metrics.py.
resource "aws_cloudwatch_metric_alarm" "api_latency_p95" {
  alarm_name          = "${local.name_prefix}-api-latency-p95"
  alarm_description   = "API p95 latency elevated. See docs/ops/CLOUDWATCH.md#api-latency-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "LatencyP95Seconds"
  namespace           = local.metric_namespace
  period              = 300
  statistic           = "Average"
  threshold           = var.api_latency_p95_threshold_seconds
  treat_missing_data  = "notBreaching"
  unit                = "Seconds"

  dimensions = {
    Environment = var.environment
  }

  alarm_actions = [aws_sns_topic.critical.arn]
  ok_actions    = [aws_sns_topic.critical.arn]

  tags = {
    "ito:role"     = "alarm"
    "ito:severity" = "warning"
  }
}

# Log-based 5xx spike (backup signal if metrics publisher is down).
resource "aws_cloudwatch_metric_alarm" "api_5xx_log_spike" {
  alarm_name          = "${local.name_prefix}-api-5xx-log-spike"
  alarm_description   = "Elevated 5xx/ERROR lines in API log group. See docs/ops/CLOUDWATCH.md#api-5xx-log-spike"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Api5xxLogCount"
  namespace           = local.metric_namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 20
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.critical.arn]

  tags = {
    "ito:role"     = "alarm"
    "ito:severity" = "warning"
  }
}
