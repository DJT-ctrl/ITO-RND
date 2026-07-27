variable "aws_region" {
  type        = string
  description = "AWS region for the MVP stack."
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

variable "vpc_cidr" {
  type        = string
  description = "CIDR for the VPC."
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR for the single public subnet."
  default     = "10.20.1.0/24"
}

variable "availability_zone" {
  type        = string
  description = "AZ for the public subnet / instance. Empty = first AZ in the region."
  default     = ""
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for the Compose host."
  default     = "t3.small"
}

variable "data_volume_size_gb" {
  type        = number
  description = "Size of the Postgres EBS data volume."
  default     = 50
}

variable "data_volume_type" {
  type        = string
  description = "EBS volume type for Postgres data."
  default     = "gp3"
}

variable "allowed_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach HTTP/HTTPS on the instance."
  default     = ["0.0.0.0/0"]
}

variable "ssh_cidrs" {
  type        = list(string)
  description = "CIDRs allowed for SSH. Empty disables SSH ingress (prefer SSM)."
  default     = []
}

variable "key_name" {
  type        = string
  description = "Optional EC2 key pair name. Leave empty when using SSM only."
  default     = ""
}

variable "enable_elastic_ip" {
  type        = bool
  description = "Allocate and associate an Elastic IP."
  default     = true
}

variable "enable_volume_protection" {
  type        = bool
  description = "Prevent Terraform destroy of the Postgres data volume (recommended for prod)."
  default     = false
}

variable "secret_arn_prefix" {
  type        = string
  description = "Secrets Manager ARN prefix the instance may read (e.g. arn:aws:secretsmanager:eu-west-2:123:secret:ito/)."
  default     = ""
}

variable "backup_bucket_name" {
  type        = string
  description = "S3 bucket name for logical DB dumps (#15). Empty skips S3 IAM statements."
  default     = ""
}

variable "create_backup_bucket" {
  type        = bool
  description = "Create the backup bucket in this stack when backup_bucket_name is set."
  default     = true
}

variable "root_volume_size_gb" {
  type        = number
  description = "Root EBS volume size for the EC2 instance."
  default     = 30
}
