locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = {
    "ito:project"    = var.project
    "ito:env"        = var.environment
    "ito:managed-by" = "terraform"
    "ito:issue"      = "17"
  }
}
