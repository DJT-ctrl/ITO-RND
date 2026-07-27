resource "aws_cloudwatch_dashboard" "ito_mvp" {
  dashboard_name = "${local.name_prefix}-mvp-health"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          markdown = "# IntoTheOpen MVP — API & host health (`${var.environment}`)\nAlarms → SNS `${aws_sns_topic.critical.name}`. Runbook: `docs/ops/CLOUDWATCH.md`."
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "API error rate (%)"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            [local.metric_namespace, "ErrorRate", "Environment", var.environment]
          ]
          annotations = {
            horizontal = [
              {
                label = "alarm"
                value = var.api_error_rate_threshold
              }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "API latency p95 (s)"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            [local.metric_namespace, "LatencyP95Seconds", "Environment", var.environment]
          ]
          annotations = {
            horizontal = [
              {
                label = "alarm"
                value = var.api_latency_p95_threshold_seconds
              }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "Host status check failed"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/EC2", "StatusCheckFailed", "InstanceId", var.compose_host_instance_id]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "Disk used percent (/)"
          region = var.aws_region
          view   = "timeSeries"
          period = 60
          metrics = [
            ["CWAgent", "disk_used_percent", "InstanceId", var.compose_host_instance_id, "path", "/", "fstype", "xfs"]
          ]
          annotations = {
            horizontal = [
              {
                label = "alarm"
                value = var.disk_used_percent_threshold
              }
            ]
          }
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 14
        width  = 24
        height = 6
        properties = {
          title  = "API log group (recent)"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.ito["api"].name}' | fields @timestamp, @message | sort @timestamp desc | limit 50"
        }
      }
    ]
  })
}
