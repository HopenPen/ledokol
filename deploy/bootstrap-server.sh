#!/usr/bin/env bash
# Ubuntu: Docker, сетевые правила, каталоги и ограниченная учётная запись CI.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu ]] || { echo 'This bootstrap supports Ubuntu' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl nginx ufw fail2ban python3-venv git openssh-client sudo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker nginx fail2ban
if [[ ! -f /swapfile ]] && [[ -z $(swapon --show --noheadings) ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
fi
cat >/etc/fail2ban/jail.d/ledokol-sshd.local <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl restart fail2ban
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
install -d -m 0755 /opt/ledokol /opt/ledokol/releases
install -d -m 0700 /opt/ledokol/shared /opt/ledokol/backups
install -d -m 0755 /opt/ledokol/shared/data/statements /var/lib/letsencrypt
id ledokol-deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash ledokol-deploy
install -d -m 0700 -o ledokol-deploy -g ledokol-deploy /home/ledokol-deploy/.ssh
printf 'ledokol-deploy ALL=(root) NOPASSWD: /usr/local/sbin/ledokol-deploy\n' >/etc/sudoers.d/ledokol-deploy
chmod 440 /etc/sudoers.d/ledokol-deploy
visudo -cf /etc/sudoers.d/ledokol-deploy
docker --version
docker compose version
