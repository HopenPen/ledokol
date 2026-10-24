#!/usr/bin/env bash
# Получает git archive через stdin. Устанавливается root в /usr/local/sbin/ledokol-deploy.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
sha=${1:?Commit SHA required}
[[ $sha =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 1; }
root=/opt/ledokol
exec 9>"$root/deploy.lock"
flock -w 900 9 || { echo 'Another deployment is running' >&2; exit 1; }
release="$root/releases/$sha"
previous=$(readlink -f "$root/current" || true)
incoming=$(mktemp -d "$root/releases/.incoming.XXXXXXXX")
archive=$(mktemp "$root/releases/.archive.XXXXXXXX")
trap 'rm -f -- "$archive"; if [[ -n ${incoming:-} ]]; then rm -rf -- "$incoming"; fi' EXIT
cat >"$archive"
python3 - "$archive" "$incoming" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    if any(member.name.split('/')[0] not in {'backend', 'frontend', 'mocks', 'deploy'} for member in archive):
        raise SystemExit('Unexpected archive contents')
    archive.extractall(sys.argv[2], filter='data')
PY
[[ -f "$incoming/deploy/compose.yml" && -f "$incoming/backend/uv.lock" ]] || { echo 'Incomplete release' >&2; exit 1; }
if [[ -d $release ]]; then
  # Повторный pipeline того же SHA использует уже проверенные исходники этого коммита.
  rm -rf -- "$incoming"
else
  mv -- "$incoming" "$release"
fi
incoming=''
export RELEASE_SHA=$sha COMPOSE_PARALLEL_LIMIT=1
compose() { docker compose -p ledokol --env-file "$root/shared/compose.env" -f "$release/deploy/compose.yml" "$@"; }
compose config --quiet
compose build api web onec
if db=$(compose ps -q db) && [[ -n $db ]]; then
  backup="$root/backups/$(date -u +%Y%m%dT%H%M%SZ)-before-$sha.dump"
  docker exec "$db" pg_dump -U cashflow -d cashflow -Fc >"$backup"
fi
verify_release() {
  compose up -d --no-build --wait --wait-timeout 240 || return 1
  curl --fail --silent --show-error http://127.0.0.1:8080/meta/categories >/dev/null || return 1
  # Первый владелец создаётся только для пустой базы. Пароль хранится в server-only app.env.
  compose exec -T api /app/.venv/bin/python - <<'PY'
from sqlalchemy import select
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal
settings = get_settings()
with SessionLocal() as session:
    if session.scalar(select(User.id).limit(1)) is None and settings.demo_password:
        session.add(User(login=settings.demo_user, password_hash=hash_password(settings.demo_password.get_secret_value())))
        session.commit()
        print('Initial owner account created')
PY
}
if ! verify_release; then
  compose logs --tail 50 api web >&2
  if [[ -n $previous && -f $previous/deploy/compose.yml ]]; then
    echo "Restoring previous containers: ${previous##*/}" >&2
    RELEASE_SHA=${previous##*/} docker compose -p ledokol --env-file "$root/shared/compose.env" \
      -f "$previous/deploy/compose.yml" up -d --no-build --wait --wait-timeout 180
  fi
  exit 1
fi
ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
printf '%s\n' "$sha" >"$root/shared/deployed-sha"
echo "Deployed $sha"
