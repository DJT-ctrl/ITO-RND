terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# Optional remote state: copy backend.tf.example → backend.tf (gitignored), then
#   terraform init -backend-config=backend.hcl
