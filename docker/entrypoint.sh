#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK_VALUE="${UMASK:-0022}"
FIX_PERMISSIONS_VALUE="${FIX_PERMISSIONS:-true}"
TZ_VALUE="${TZ:-Europe/London}"

if ! [[ "$PUID" =~ ^[0-9]+$ && "$PGID" =~ ^[0-9]+$ ]]; then
  echo "ERROR: PUID and PGID must be numeric." >&2
  exit 1
fi
if ! [[ "$UMASK_VALUE" =~ ^0?[0-7]{3}$ ]]; then
  echo "ERROR: UMASK must be an octal value such as 0022 or 0002." >&2
  exit 1
fi

umask "$UMASK_VALUE"

if [ -f "/usr/share/zoneinfo/$TZ_VALUE" ]; then
  ln -snf "/usr/share/zoneinfo/$TZ_VALUE" /etc/localtime
  echo "$TZ_VALUE" > /etc/timezone
else
  echo "WARNING: Unknown TZ '$TZ_VALUE'; retaining container default." >&2
fi

groupmod -o -g "$PGID" makervault
usermod -o -u "$PUID" -g "$PGID" makervault

mkdir -p /app/media /app/staticfiles /app/run /home/makervault
if [ "$FIX_PERMISSIONS_VALUE" = "true" ] || [ "$FIX_PERMISSIONS_VALUE" = "1" ]; then
  chown -R "$PUID:$PGID" /app/media /app/staticfiles /app/run /home/makervault
else
  chown "$PUID:$PGID" /app/media /app/staticfiles /app/run 2>/dev/null || true
fi

if [ "${DJANGO_DEBUG:-false}" != "true" ]; then
  SECRET_VALUE="${DJANGO_SECRET_KEY:-}"
  if [ -z "$SECRET_VALUE" ] || [ "$SECRET_VALUE" = "CHANGE_ME_TO_A_LONG_RANDOM_VALUE" ] || [ "${#SECRET_VALUE}" -lt 32 ]; then
    echo "ERROR: Set DJANGO_SECRET_KEY to a strong value (32+ characters) before running with DJANGO_DEBUG=false." >&2
    exit 1
  fi
fi

cd /app/backend

echo "Applying database migrations..."
gosu makervault python manage.py migrate --noinput
gosu makervault python manage.py seed_roles

echo "Ensuring starter catalogue..."
gosu makervault python manage.py seed_catalogue

echo "Catalogue maintenance is handled by the persistent scheduler."

echo "Collecting static files..."
gosu makervault python manage.py collectstatic --noinput --clear >/dev/null

if [ -n "${MAKERVAULT_ADMIN_PASSWORD:-}" ]; then
  echo "Ensuring configured admin user exists..."
  gosu makervault python manage.py ensure_admin
fi

exec "$@"
