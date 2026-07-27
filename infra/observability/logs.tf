resource "aws_cloudwatch_log_group" "ito" {
  for_each = local.log_groups

  name              = each.value
  retention_in_days = var.log_retention_days

  tags = {
    Name       = each.value
    "ito:role" = "logs-${each.key}"
  }
}

# Count HTTP 5xx lines from API container logs (JSON or plain access lines).
resource "aws_cloudwatch_log_metric_filter" "api_5xx" {
  name           = "${local.name_prefix}-api-5xx"
  log_group_name = aws_cloudwatch_log_group.ito["api"].name
  pattern        = "?\" 5\" ?\"status\":5 ?\"StatusCode\":5 ?ERROR"

  metric_transformation {
    name          = "Api5xxLogCount"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}
