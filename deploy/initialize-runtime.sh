#!/usr/bin/env bash
# Секреты генерируются на сервере и сохраняются между релизами.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
python3 - "${1:?Public HTTPS URL required}" <<'PY'
import json, os, pathlib, secrets, sys
from urllib.parse import urlsplit
url = sys.argv[1].rstrip('/')
parsed = urlsplit(url)
if parsed.scheme != 'https' or not parsed.hostname or any(c in url for c in '\n\r'):
    raise SystemExit('A public HTTPS URL is required')
os.umask(0o077)
root = pathlib.Path('/opt/ledokol/shared')
compose = root / 'compose.env'
if not compose.exists():
    compose.write_text('POSTGRES_PASSWORD=' + secrets.token_hex(32) + '\nMOCK_TOKEN=' + secrets.token_hex(32) + '\n')
values = dict(line.split('=', 1) for line in compose.read_text().splitlines() if '=' in line)
app = root / 'app.env'
if not app.exists():
    password = secrets.token_urlsafe(24)
    settings = {
        # Встроенный Mailpit использует SMTP без TLS. Почтовую логику прототипа сохраняем.
        'CASHFLOW_ENV': 'dev',
        'CASHFLOW_JWT_SECRET': secrets.token_hex(32),
        'CASHFLOW_CORS_ORIGINS': json.dumps([url]),
        'CASHFLOW_PUBLIC_APP_URL': url,
        'CASHFLOW_ONEC_TOKEN': values['MOCK_TOKEN'],
        'CASHFLOW_FNS_TOKEN': values['MOCK_TOKEN'],
        'CASHFLOW_LLM_PROVIDER': 'none',
        'CASHFLOW_DEMO_USER': 'owner',
        'CASHFLOW_DEMO_PASSWORD': password,
    }
    app.write_text(''.join(f'{key}={value}\n' for key, value in settings.items()))
    (root / 'operator-access.txt').write_text(f'URL: {url}\nLogin: owner\nPassword: {password}\n')
print('Server runtime configuration ready; secret values were not printed')
PY
if [[ ! -f /opt/ledokol/shared/gitlab-ci-ed25519 ]]; then
  ssh-keygen -q -t ed25519 -N '' -C gitlab-ledokol-deploy -f /opt/ledokol/shared/gitlab-ci-ed25519
fi
{ printf 'restrict,command="/usr/local/sbin/ledokol-ssh" '; cat /opt/ledokol/shared/gitlab-ci-ed25519.pub; } \
  >/home/ledokol-deploy/.ssh/authorized_keys
chown ledokol-deploy:ledokol-deploy /home/ledokol-deploy/.ssh/authorized_keys
chmod 600 /home/ledokol-deploy/.ssh/authorized_keys
