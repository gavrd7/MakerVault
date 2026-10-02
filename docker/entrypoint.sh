#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK_VALUE="${UMASK:-0022}"
FIX_PERMISSIONS_VALUE="${FIX_PERMISSIONS:-true}"
TZ_VALUE="${TZ:-Europe/London}"
STORAGE_KEY_FILE="${MAKERVAULT_STORAGE_KEY_FILE:-/app/keys/private_storage.key}"

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

mkdir -p /app/media /app/keys /app/backups /app/staticfiles /app/run /home/makervault
if [ "$FIX_PERMISSIONS_VALUE" = "true" ] || [ "$FIX_PERMISSIONS_VALUE" = "1" ]; then
  chown -R "$PUID:$PGID" /app/media /app/keys /app/backups /app/staticfiles /app/run /home/makervault
else
  chown "$PUID:$PGID" /app/media /app/keys /app/backups /app/staticfiles /app/run 2>/dev/null || true
fi

# Keep the private-file encryption key outside the media volume. The default
# Docker deployment generates it once in the dedicated key volume.
if [ -z "${MAKERVAULT_STORAGE_KEY:-}" ]; then
  mkdir -p "$(dirname "$STORAGE_KEY_FILE")"
  if [ ! -s "$STORAGE_KEY_FILE" ]; then
    # Never silently replace a lost key when encrypted blobs already exist.
    # A newly generated key would make those blobs permanently unreadable.
    if [ -d /app/media/private ] && find /app/media/private -type f -name '*.blob' -print -quit | grep -q .; then
      echo "ERROR: Encrypted MakerVault private files exist but the storage key is missing." >&2
      echo "Restore KEY_STORAGE / MAKERVAULT_STORAGE_KEY_FILE from backup. A new key cannot decrypt existing data." >&2
      exit 1
    fi
    echo "Generating MakerVault private-storage encryption key..."
    python - "$STORAGE_KEY_FILE" <<'PY'
import base64
import os
import sys

path = sys.argv[1]
value = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
with open(path, "w", encoding="ascii") as handle:
    handle.write(value + "\n")
PY
  fi
  chown "$PUID:$PGID" "$STORAGE_KEY_FILE" 2>/dev/null || true
  chmod 600 "$STORAGE_KEY_FILE" 2>/dev/null || true
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

echo "Recovering interrupted backup state..."
gosu makervault python manage.py backup_bundle recover-stale

echo "Encrypting any legacy user-private media..."
if ! gosu makervault python manage.py migrate_private_storage; then
  echo "WARNING: Some legacy private media could not be encrypted. MakerVault will continue and retry on the next start." >&2
fi

echo "Ensuring starter catalogue..."
gosu makervault python manage.py seed_catalogue

echo "Ensuring 3D printer catalogue..."
gosu makervault python manage.py seed_printing_catalogue

if [ "${SYNC_ORCASLICER_PRINTER_CATALOGUE:-true}" = "true" ] || [ "${SYNC_ORCASLICER_PRINTER_CATALOGUE:-true}" = "1" ]; then
  echo "Expanding sparse 3D printer catalogue from OrcaSlicer..."
  gosu makervault python manage.py sync_orcaslicer_printer_catalogue --best-effort --if-sparse 100
fi

echo "Catalogue maintenance is handled by the persistent scheduler."

echo "Collecting static files..."
gosu makervault python manage.py collectstatic --noinput --clear >/dev/null

if [ -n "${MAKERVAULT_ADMIN_PASSWORD:-}" ]; then
  echo "Ensuring configured admin user exists..."
  gosu makervault python manage.py ensure_admin
fi

exec "$@"
