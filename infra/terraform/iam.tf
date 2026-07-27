data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "compose_host" {
  name               = "${local.name_prefix}-compose-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = {
    Name       = "${local.name_prefix}-compose-host-role"
    "ito:role" = "compose-host"
  }
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.compose_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "compose_host" {
  statement {
    sid       = "ReadRuntimeSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = local.secret_arns
  }

  dynamic "statement" {
    for_each = var.backup_bucket_name != "" ? [var.backup_bucket_name] : []
    content {
      sid = "BackupBucketObjects"
      actions = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
      ]
      resources = ["arn:aws:s3:::${statement.value}/*"]
    }
  }

  dynamic "statement" {
    for_each = var.backup_bucket_name != "" ? [var.backup_bucket_name] : []
    content {
      sid       = "BackupBucketList"
      actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
      resources = ["arn:aws:s3:::${statement.value}"]
    }
  }
}

resource "aws_iam_role_policy" "compose_host" {
  name   = "${local.name_prefix}-compose-host"
  role   = aws_iam_role.compose_host.id
  policy = data.aws_iam_policy_document.compose_host.json
}

resource "aws_iam_instance_profile" "compose_host" {
  name = "${local.name_prefix}-compose-host"
  role = aws_iam_role.compose_host.name

  tags = {
    Name       = "${local.name_prefix}-compose-host-profile"
    "ito:role" = "compose-host"
  }
}

resource "aws_s3_bucket" "backups" {
  count  = var.backup_bucket_name != "" && var.create_backup_bucket ? 1 : 0
  bucket = var.backup_bucket_name

  tags = {
    Name       = var.backup_bucket_name
    "ito:role" = "backup"
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  count  = length(aws_s3_bucket.backups)
  bucket = aws_s3_bucket.backups[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "backups" {
  count  = length(aws_s3_bucket.backups)
  bucket = aws_s3_bucket.backups[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  count  = length(aws_s3_bucket.backups)
  bucket = aws_s3_bucket.backups[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
