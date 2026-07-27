locals {
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    dnf update -y
    dnf install -y docker git
    systemctl enable --now docker
    usermod -aG docker ec2-user || true

    # Docker Compose v2 plugin
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    # Mount Postgres data volume if present (device name may vary — nvme on Nitro)
    mkdir -p /data/postgres
    DATA_DEV="$(lsblk -ndo NAME,TYPE,MOUNTPOINT | awk '$2=="disk" && $3=="" {print $1}' | grep -vE '^(nvme0n1|xvda)$' | head -1 || true)"
    if [[ -n "$${DATA_DEV}" ]]; then
      if ! blkid "/dev/$${DATA_DEV}" >/dev/null 2>&1; then
        mkfs.xfs "/dev/$${DATA_DEV}"
      fi
      UUID="$(blkid -s UUID -o value "/dev/$${DATA_DEV}")"
      grep -q "$UUID" /etc/fstab || echo "UUID=$${UUID} /data/postgres xfs defaults,nofail 0 2" >> /etc/fstab
      mount -a || mount "/dev/$${DATA_DEV}" /data/postgres
    fi
    chown -R 999:999 /data/postgres || true

    mkdir -p /opt/ito-rnd /etc/ito /run/ito
    echo "ITO bootstrap complete — clone repo and enable ito-stack (#20)" > /opt/ito-rnd/BOOTSTRAP.txt
  EOF
}

resource "aws_instance" "compose_host" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.compose_host.id]
  iam_instance_profile   = aws_iam_instance_profile.compose_host.name
  key_name               = var.key_name != "" ? var.key_name : null
  user_data              = local.user_data

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
    encrypted   = true
  }

  tags = {
    Name       = "${local.name_prefix}-compose-host"
    "ito:role" = "compose-host"
  }

  volume_tags = {
    Name       = "${local.name_prefix}-compose-root"
    "ito:role" = "compose-host"
  }
}

resource "aws_eip" "compose_host" {
  count  = var.enable_elastic_ip ? 1 : 0
  domain = "vpc"

  tags = {
    Name       = "${local.name_prefix}-compose-eip"
    "ito:role" = "compose-host"
  }
}

resource "aws_eip_association" "compose_host" {
  count         = var.enable_elastic_ip ? 1 : 0
  instance_id   = aws_instance.compose_host.id
  allocation_id = aws_eip.compose_host[0].id
}
