resource "aws_security_group" "compose_host" {
  name        = "${local.name_prefix}-compose-host"
  description = "ITO Compose host — HTTPS/HTTP public; Postgres not exposed"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name       = "${local.name_prefix}-compose-host-sg"
    "ito:role" = "compose-host"
  }
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each = toset(var.allowed_cidrs)

  security_group_id = aws_security_group.compose_host.id
  description       = "HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  for_each = toset(var.allowed_cidrs)

  security_group_id = aws_security_group.compose_host.id
  description       = "HTTP (redirect to HTTPS via Nginx — #14)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each = toset(var.ssh_cidrs)

  security_group_id = aws_security_group.compose_host.id
  description       = "SSH admin (prefer SSM Session Manager)"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.compose_host.id
  description       = "Egress for packages, Secrets Manager, S3, Gemini/Apify"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
