locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = {
    "ito:project"    = var.project
    "ito:env"        = var.environment
    "ito:managed-by" = "terraform"
    "ito:issue"      = "16"
  }

  log_groups = {
    api    = "/ito/${var.environment}/api"
    host   = "/ito/${var.environment}/host"
    docker = "/ito/${var.environment}/docker"
  }

  metric_namespace = "ITO/API"
}
