locals {
  name_prefix = "${var.project}-${var.environment}"

  az = var.availability_zone != "" ? var.availability_zone : data.aws_availability_zones.available.names[0]

  common_tags = {
    "ito:project"    = var.project
    "ito:env"        = var.environment
    "ito:managed-by" = "terraform"
    "ito:issue"      = "12"
  }

  secret_arns = var.secret_arn_prefix != "" ? ["${var.secret_arn_prefix}*"] : ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:ito/*"]
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
