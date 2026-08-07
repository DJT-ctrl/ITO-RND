resource "aws_wafv2_ip_set" "allow" {
  count = length(var.ip_allowlist) > 0 ? 1 : 0

  name               = "${local.name_prefix}-waf-allow"
  description        = "Break-glass / office allowlist (#17)"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = var.ip_allowlist

  tags = {
    Name       = "${local.name_prefix}-waf-allow"
    "ito:role" = "waf-allowlist"
  }
}

resource "aws_wafv2_ip_set" "block" {
  count = length(var.ip_blocklist) > 0 ? 1 : 0

  name               = "${local.name_prefix}-waf-block"
  description        = "Manual abuse blocklist (#17)"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = var.ip_blocklist

  tags = {
    Name       = "${local.name_prefix}-waf-block"
    "ito:role" = "waf-blocklist"
  }
}

resource "aws_wafv2_web_acl" "api" {
  name        = "${local.name_prefix}-api-waf"
  description = "Post-launch API edge protections (#17)"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Highest priority: explicit allow exceptions.
  dynamic "rule" {
    for_each = length(var.ip_allowlist) > 0 ? [1] : []
    content {
      name     = "IpAllowlist"
      priority = 0

      action {
        allow {}
      }

      statement {
        ip_set_reference_statement {
          arn = aws_wafv2_ip_set.allow[0].arn
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.name_prefix}-IpAllowlist"
        sampled_requests_enabled   = true
      }
    }
  }

  dynamic "rule" {
    for_each = length(var.ip_blocklist) > 0 ? [1] : []
    content {
      name     = "IpBlocklist"
      priority = 1

      action {
        block {}
      }

      statement {
        ip_set_reference_statement {
          arn = aws_wafv2_ip_set.block[0].arn
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.name_prefix}-IpBlocklist"
        sampled_requests_enabled   = true
      }
    }
  }

  rule {
    name     = "AWSManagedRulesAmazonIpReputationList"
    priority = 10

    override_action {
      dynamic "none" {
        for_each = var.enable_blocking ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.enable_blocking ? [] : [1]
        content {}
      }
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-IpReputation"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 20

    override_action {
      dynamic "none" {
        for_each = var.enable_blocking ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.enable_blocking ? [] : [1]
        content {}
      }
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # API JSON bodies can trip size restrictions — review in COUNT then tune.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 30

    override_action {
      dynamic "none" {
        for_each = var.enable_blocking ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.enable_blocking ? [] : [1]
        content {}
      }
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 40

    override_action {
      dynamic "none" {
        for_each = var.enable_blocking ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.enable_blocking ? [] : [1]
        content {}
      }
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-SQLi"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimitPerIp"
    priority = 50

    action {
      dynamic "block" {
        for_each = var.enable_blocking ? [1] : []
        content {}
      }
      dynamic "count" {
        for_each = var.enable_blocking ? [] : [1]
        content {}
      }
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_requests_per_5_minutes
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-RateLimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-api-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Name       = "${local.name_prefix}-api-waf"
    "ito:role" = "waf"
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  count = var.alb_arn != "" ? 1 : 0

  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.api.arn
}
