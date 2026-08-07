output "environment" {
  value       = var.environment
  description = "Deployed environment name."
}

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC id."
}

output "public_subnet_id" {
  value       = aws_subnet.public.id
  description = "Public subnet id."
}

output "compose_host_instance_id" {
  value       = aws_instance.compose_host.id
  description = "EC2 instance id for the Compose host."
}

output "compose_host_private_ip" {
  value       = aws_instance.compose_host.private_ip
  description = "Private IP of the Compose host."
}

output "compose_host_public_ip" {
  value       = var.enable_elastic_ip ? aws_eip.compose_host[0].public_ip : aws_instance.compose_host.public_ip
  description = "Public IP (Elastic IP when enabled)."
}

output "compose_host_security_group_id" {
  value       = aws_security_group.compose_host.id
  description = "Security group attached to the Compose host."
}

output "compose_host_instance_profile" {
  value       = aws_iam_instance_profile.compose_host.name
  description = "Instance profile name."
}

output "compose_host_role_arn" {
  value       = aws_iam_role.compose_host.arn
  description = "IAM role ARN for the Compose host."
}

output "postgres_data_volume_id" {
  value       = aws_ebs_volume.postgres_data.id
  description = "EBS volume id for Postgres data (tag ito:role=postgres-data)."
}

output "backup_bucket_name" {
  value       = var.backup_bucket_name
  description = "Backup bucket name (empty if unused)."
}

output "db_data_path_hint" {
  value       = "/data/postgres"
  description = "Suggested DB_DATA_PATH on the host after user-data mount."
}

output "next_steps" {
  value = <<-EOT
    1. SSM into ${aws_instance.compose_host.id}
    2. Clone repo to /opt/ito-rnd; set DB_DATA_PATH=/data/postgres
    3. Configure Secrets Manager + ito-stack (#13 / #20)
    4. Enable backup timer + DLM on volume ${aws_ebs_volume.postgres_data.id} (#15)
  EOT
}
