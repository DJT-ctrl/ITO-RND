resource "aws_budgets_budget" "monthly_overall" {
  name         = "${local.name_prefix}-monthly-overall"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.actual_alert_thresholds
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_sns_topic_arns  = local.subscriber_sns
      subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.forecast_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  tags = {
    Name           = "${local.name_prefix}-monthly-overall"
    "ito:role"     = "budget"
    "ito:budget"   = "overall"
  }
}

resource "aws_budgets_budget" "monthly_ec2" {
  name         = "${local.name_prefix}-monthly-ec2"
  budget_type  = "COST"
  limit_amount = tostring(var.ec2_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "Service"
    values = [
      "Amazon Elastic Compute Cloud - Compute",
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.forecast_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  tags = {
    Name         = "${local.name_prefix}-monthly-ec2"
    "ito:role"   = "budget"
    "ito:budget" = "ec2"
  }
}

resource "aws_budgets_budget" "monthly_ebs" {
  name         = "${local.name_prefix}-monthly-ebs"
  budget_type  = "COST"
  limit_amount = tostring(var.ebs_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "Service"
    values = [
      "Amazon Elastic Block Store",
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.forecast_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  tags = {
    Name         = "${local.name_prefix}-monthly-ebs"
    "ito:role"   = "budget"
    "ito:budget" = "ebs"
  }
}

resource "aws_budgets_budget" "monthly_cloudwatch" {
  name         = "${local.name_prefix}-monthly-cloudwatch"
  budget_type  = "COST"
  limit_amount = tostring(var.cloudwatch_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "Service"
    values = [
      "Amazon CloudWatch",
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.forecast_alert_threshold
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = local.subscriber_sns
    subscriber_email_addresses = length(local.subscriber_emails) > 0 ? local.subscriber_emails : null
  }

  tags = {
    Name         = "${local.name_prefix}-monthly-cloudwatch"
    "ito:role"   = "budget"
    "ito:budget" = "cloudwatch"
  }
}
