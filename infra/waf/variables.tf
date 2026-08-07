variable "aws_region" {
  type        = string
  description = "Region for regional WAFv2 Web ACL (must match the ALB)."
  default     = "eu-west-2"
}

variable "environment" {
  type        = string
  description = "Environment name: staging or prod (post-launch)."

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "project" {
  type        = string
  description = "Project name prefix."
  default     = "intotheopen"
}

variable "alb_arn" {
  type        = string
  description = "Application Load Balancer ARN to associate. Empty skips association (Web ACL still created)."
  default     = ""
}

variable "enable_blocking" {
  type        = bool
  description = "When false (staged rollout), managed rules use Count overrides. When true, enforce Block."
  default     = false
}

variable "rate_limit_requests_per_5_minutes" {
  type        = number
  description = "Per-IP rate-based rule threshold (edge bot/rate control)."
  default     = 2000
}

variable "ip_allowlist" {
  type        = list(string)
  description = "CIDRs always allowed (office / monitoring / break-glass). Empty = no allowlist rule."
  default     = []
}

variable "ip_blocklist" {
  type        = list(string)
  description = "CIDRs always blocked (manual exception / abuse). Empty = no blocklist rule."
  default     = []
}
