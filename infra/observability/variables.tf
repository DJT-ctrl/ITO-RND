variable "aws_region" {
  type        = string
  description = "AWS region (should match the Compose host from #12)."
  default     = "eu-west-2"
}

variable "environment" {
  type        = string
  description = "Environment name: dev, staging, or prod."

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  type        = string
  description = "Project tag value."
  default     = "intotheopen"
}

variable "compose_host_instance_id" {
  type        = string
  description = "EC2 instance id from infra/terraform (#12). Required for host/disk alarms."
}

variable "compose_host_role_name" {
  type        = string
  description = "IAM role name on the Compose host (attach CloudWatch agent permissions)."
  default     = ""
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch Logs retention (MVP cost control)."
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch-supported retention value."
  }
}

variable "alert_email" {
  type        = string
  description = "Optional email subscribed to the critical SNS topic (confirm via AWS email)."
  default     = ""
}

variable "alert_https_endpoint" {
  type        = string
  description = "Optional HTTPS endpoint for Slack (Chatbot/webhook) or PagerDuty Events API."
  default     = ""
}

variable "api_error_rate_threshold" {
  type        = number
  description = "Alarm when ITO/API ErrorRate (%) exceeds this over 5 minutes."
  default     = 5
}

variable "api_latency_p95_threshold_seconds" {
  type        = number
  description = "Alarm when ITO/API LatencyP95Seconds exceeds this over 5 minutes."
  default     = 30
}

variable "disk_used_percent_threshold" {
  type        = number
  description = "Alarm when CWAgent disk_used_percent on / exceeds this."
  default     = 85
}
