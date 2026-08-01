# Attach CloudWatch agent + logs permissions to the Compose host role from #12.
resource "aws_iam_role_policy_attachment" "cw_agent" {
  count = var.compose_host_role_name != "" ? 1 : 0

  role       = var.compose_host_role_name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "cw_logs_extra" {
  statement {
    sid = "CreateAndWriteItoLogGroups"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
      "logs:PutRetentionPolicy",
    ]
    resources = [
      for name in values(local.log_groups) :
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${name}:*"
    ]
  }

  statement {
    sid = "DescribeItoLogGroups"
    actions = [
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  statement {
    sid = "PutCustomApiMetrics"
    actions = [
      "cloudwatch:PutMetricData",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.metric_namespace]
    }
  }
}

resource "aws_iam_role_policy" "cw_logs_extra" {
  count = var.compose_host_role_name != "" ? 1 : 0

  name   = "${local.name_prefix}-cloudwatch-logs"
  role   = var.compose_host_role_name
  policy = data.aws_iam_policy_document.cw_logs_extra.json
}
