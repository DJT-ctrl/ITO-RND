resource "aws_ebs_volume" "postgres_data" {
  availability_zone = local.az
  size              = var.data_volume_size_gb
  type              = var.data_volume_type
  encrypted         = true

  tags = {
    Name       = "${local.name_prefix}-postgres-data"
    "ito:role" = "postgres-data"
  }

  lifecycle {
    prevent_destroy = false
  }
}

# Optional hard protection for prod — toggle via variable by swapping module later.
# Terraform cannot interpolate lifecycle prevent_destroy; document enabling
# manually in prod.tfvars comments / ops checklist when enable_volume_protection=true.

resource "aws_volume_attachment" "postgres_data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.postgres_data.id
  instance_id = aws_instance.compose_host.id
}

check "volume_protection_reminder" {
  assert {
    condition     = !var.enable_volume_protection || var.environment == "prod"
    error_message = "enable_volume_protection is intended for prod; set environment=prod or disable the flag."
  }
}
