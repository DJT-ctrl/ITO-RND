resource "aws_sns_topic" "critical" {
  name = "${local.name_prefix}-critical-alerts"

  tags = {
    Name       = "${local.name_prefix}-critical-alerts"
    "ito:role" = "alerting"
  }
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.critical.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Slack (via AWS Chatbot HTTPS / Incoming Webhook bridge) or PagerDuty Events v2.
resource "aws_sns_topic_subscription" "https" {
  count = var.alert_https_endpoint != "" ? 1 : 0

  topic_arn = aws_sns_topic.critical.arn
  protocol  = "https"
  endpoint  = var.alert_https_endpoint
}

resource "aws_sns_topic_policy" "critical" {
  arn = aws_sns_topic.critical.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudWatchAlarms"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.critical.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

data "aws_caller_identity" "current" {}
