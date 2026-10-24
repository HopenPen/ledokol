#!/usr/bin/env bash
# HTTPS для публичного IP; Certbot обновляет сертификат без остановки nginx.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
address=${1:?Public IPv4 address required}
python3 - "$address" <<'PY'
import ipaddress, sys
address = ipaddress.IPv4Address(sys.argv[1])
if not address.is_global:
    raise SystemExit('A public IPv4 address is required')
PY
if [[ ! -x /opt/certbot/bin/certbot ]]; then
  python3 -m venv /opt/certbot
  /opt/certbot/bin/pip --quiet install 'certbot>=5.4,<6'
fi
install -d -m 0755 /var/lib/letsencrypt
cat >/etc/nginx/sites-available/ledokol <<'EOF'
server {
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name _;
  client_max_body_size 50m;
  location /.well-known/acme-challenge/ { root /var/lib/letsencrypt; }
  location / { proxy_pass http://127.0.0.1:8080; }
}
EOF
if [[ -L /etc/nginx/sites-enabled/default ]]; then unlink /etc/nginx/sites-enabled/default; fi
ln -sfn /etc/nginx/sites-available/ledokol /etc/nginx/sites-enabled/ledokol
nginx -t
systemctl reload nginx
if [[ ! -f /etc/letsencrypt/live/$address/fullchain.pem ]]; then
  /opt/certbot/bin/certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --staging --config-dir /etc/letsencrypt-staging --work-dir /var/lib/letsencrypt-staging \
    --logs-dir /var/log/letsencrypt-staging --preferred-profile shortlived \
    --webroot --webroot-path /var/lib/letsencrypt --ip-address "$address"
  /opt/certbot/bin/certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
    --preferred-profile shortlived --webroot --webroot-path /var/lib/letsencrypt --ip-address "$address"
fi
cat >/etc/nginx/sites-available/ledokol <<EOF
server {
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name $address;
  location /.well-known/acme-challenge/ { root /var/lib/letsencrypt; }
  location / { return 301 https://$address\$request_uri; }
}
server {
  listen 443 ssl default_server;
  listen [::]:443 ssl default_server;
  server_name $address;
  ssl_certificate /etc/letsencrypt/live/$address/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/$address/privkey.pem;
  ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 50m;
  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 120s;
  }
}
EOF
nginx -t
systemctl reload nginx
install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/reload-nginx <<'EOF'
#!/bin/sh
set -eu
nginx -t
systemctl reload nginx
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
cat >/etc/systemd/system/ledokol-certificate.service <<'EOF'
[Unit]
Description=Renew Ledokol IP certificate
After=network-online.target nginx.service
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/certbot/bin/certbot renew --quiet
EOF
cat >/etc/systemd/system/ledokol-certificate.timer <<'EOF'
[Unit]
Description=Check Ledokol certificate every six hours
[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
RandomizedDelaySec=5min
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now ledokol-certificate.timer
echo "HTTPS configured for $address"
