#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
UMASK_VALUE="${UMASK:-0022}"
FIX_PERMISSIONS_VALUE="${FIX_PERMISSIONS:-true}"
TZ_VALUE="${TZ:-Europe/London}"
STORAGE_KEY_FILE="${MAKERVAULT_STORAGE_KEY_FILE:-/app/keys/private_storage.key}"
HTTPS_ENABLED="${MAKERVAULT_HTTPS_ENABLED:-false}"
HTTPS_SELF_SIGNED="${MAKERVAULT_HTTPS_SELF_SIGNED:-false}"
TLS_CERT_FILE="${MAKERVAULT_TLS_CERT_FILE:-/app/keys/tls/cert.pem}"
TLS_KEY_FILE="${MAKERVAULT_TLS_KEY_FILE:-/app/keys/tls/key.pem}"

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

mkdir -p /app/media /app/keys /app/keys/tls /app/backups /app/staticfiles /app/run /home/makervault
if [ "$FIX_PERMISSIONS_VALUE" = "true" ] || [ "$FIX_PERMISSIONS_VALUE" = "1" ]; then
  chown -R "$PUID:$PGID" /app/media /app/keys /app/backups /app/staticfiles /app/run /home/makervault
else
  chown "$PUID:$PGID" /app/media /app/keys /app/backups /app/staticfiles /app/run 2>/dev/null || true
fi


is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if is_true "$HTTPS_ENABLED"; then
  mkdir -p "$(dirname "$TLS_CERT_FILE")" "$(dirname "$TLS_KEY_FILE")"

  if is_true "$HTTPS_SELF_SIGNED"; then
    if [ ! -e "$TLS_CERT_FILE" ] && [ ! -e "$TLS_KEY_FILE" ]; then
      echo "Generating persistent MakerVault self-signed HTTPS certificate..."
      mapfile -t TLS_IDENTITY < <(
        python - "${MAKERVAULT_HTTPS_SELF_SIGNED_NAMES:-}" "${DJANGO_ALLOWED_HOSTS:-}" <<'PY'
import ipaddress
import re
import sys

explicit, allowed = sys.argv[1], sys.argv[2]
raw = explicit or allowed or "localhost,127.0.0.1"
values = []
for item in raw.split(","):
    item = item.strip()
    if not item or item == "*" or item.startswith(".") or "*" in item:
        continue
    if item not in values:
        values.append(item)

if "localhost" not in values:
    values.insert(0, "localhost")

san = []
for value in values:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if re.fullmatch(r"[A-Za-z0-9.-]+", value):
            san.append(f"DNS:{value}")
    else:
        san.append(f"IP:{value}")

if not san:
    san = ["DNS:localhost", "IP:127.0.0.1"]
print(values[0] if values else "localhost")
print(",".join(san))
PY
      )
      TLS_CN="${TLS_IDENTITY[0]:-localhost}"
      TLS_SAN="${TLS_IDENTITY[1]:-DNS:localhost,IP:127.0.0.1}"
      openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
        -keyout "$TLS_KEY_FILE" \
        -out "$TLS_CERT_FILE" \
        -subj "/CN=$TLS_CN" \
        -addext "subjectAltName=$TLS_SAN" \
        -addext "basicConstraints=critical,CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth"
    elif [ ! -s "$TLS_CERT_FILE" ] || [ ! -s "$TLS_KEY_FILE" ]; then
      echo "ERROR: Native HTTPS self-signed storage is incomplete; refusing to replace only one TLS file." >&2
      echo "Restore the missing TLS file or deliberately remove both certificate and key to regenerate them." >&2
      exit 1
    fi
  fi

  if [ ! -s "$TLS_CERT_FILE" ] || [ ! -s "$TLS_KEY_FILE" ]; then
    echo "ERROR: MAKERVAULT_HTTPS_ENABLED=true requires a certificate and private key." >&2
    echo "Provide them under KEY_STORAGE/tls or enable MAKERVAULT_HTTPS_SELF_SIGNED=true." >&2
    exit 1
  fi

  if ! openssl x509 -in "$TLS_CERT_FILE" -noout >/dev/null 2>&1; then
    echo "ERROR: MakerVault HTTPS certificate is not a readable PEM X.509 certificate." >&2
    exit 1
  fi
  if ! openssl pkey -in "$TLS_KEY_FILE" -noout -check >/dev/null 2>&1; then
    echo "ERROR: MakerVault HTTPS private key is not a readable PEM private key." >&2
    exit 1
  fi

  CERT_PUB="$(openssl x509 -in "$TLS_CERT_FILE" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  KEY_PUB="$(openssl pkey -in "$TLS_KEY_FILE" -pubout -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
  if [ "$CERT_PUB" != "$KEY_PUB" ]; then
    echo "ERROR: MakerVault HTTPS certificate and private key do not match." >&2
    exit 1
  fi

  chown "$PUID:$PGID" "$TLS_CERT_FILE" "$TLS_KEY_FILE" 2>/dev/null || true
  chmod 644 "$TLS_CERT_FILE" 2>/dev/null || true
  chmod 600 "$TLS_KEY_FILE" 2>/dev/null || true
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
