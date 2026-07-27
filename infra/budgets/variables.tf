variable "aws_region" {
  type        = string
  description = "AWS region for SNS (Budgets themselves are account-global)."
  default     = "eu-west-2"
}

variable "environment" {
  type        = string
  description = "Environment label for naming (dev / staging / prod)."

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  type        = string
  description = "Project tag / name prefix."
  default     = "intotheopen"
}

variable "monthly_budget_usd" {
  type        = number
  description = "Overall monthly COST budget (USD) for the low-cost MVP."
  default     = 80
}

variable "ec2_budget_usd" {
  type        = number
  description = "Monthly budget slice for EC2 compute."
  default     = 45
}

variable "ebs_budget_usd" {
  type        = number
  description = "Monthly budget slice for EBS storage."
  default     = 15
}

variable "cloudwatch_budget_usd" {
  type        = number
  description = "Monthly budget slice for CloudWatch (logs/metrics/alarms)."
  default     = 12
}

variable "alert_emails" {
  type        = list(string)
  description = "Owner emails notified by AWS Budgets (and optional SNS email)."
  default     = []
}

variable "alert_https_endpoint" {
  type        = string
  description = "Optional HTTPS endpoint (Slack Chatbot/webhook or PagerDuty) via SNS."
  default     = ""
}

variable "actual_alert_thresholds" {
  type        = list(number)
  description = "ACTUAL spend % thresholds that notify before overrun."
  default     = [50, 80, 100]
}

variable "forecast_alert_threshold" {
  type        = number
  description = "FORECASTED spend % threshold (notify before month-end overrun)."
  default     = 100
}
