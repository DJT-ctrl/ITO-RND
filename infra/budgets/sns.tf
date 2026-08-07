data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "budget_alerts" {
  name = "${local.name_prefix}-budget-alerts"

  tags = {
    Name       = "${local.name_prefix}-budget-alerts"
    "ito:role" = "budget-alerting"
  }
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sns_topic_subscription" "https" {
  count = var.alert_https_endpoint != "" ? 1 : 0

  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "https"
  endpoint  = var.alert_https_endpoint
}

# AWS Budgets publishes to SNS; topic policy must allow budgets.amazonaws.com.
resource "aws_sns_topic_policy" "budget_alerts" {
  arn = aws_sns_topic.budget_alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "${local.name_prefix}-budget-alerts-policy"
    Statement = [
      {
        Sid       = "AWSBudgetsSNSPublishingPermissions"
        Effect    = "Allow"
        Principal = { Service = "budgets.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.budget_alerts.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/*"
          }
        }
      }
    ]
  })
}
