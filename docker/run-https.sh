#!/usr/bin/env bash
set -euo pipefail

enabled="${MAKERVAULT_HTTPS_ENABLED:-false}"
case "${enabled,,}" in
  1|true|yes|on) ;;
  *)
    echo "Native HTTPS listener disabled."
    exec sleep infinity
    ;;
esac

cert="${MAKERVAULT_TLS_CERT_FILE:-/app/tls/cert.pem}"
key="${MAKERVAULT_TLS_KEY_FILE:-/app/tls/key.pem}"
workers="${HTTPS_WEB_CONCURRENCY:-1}"
timeout="${GUNICORN_TIMEOUT:-120}"

if [ ! -r "$cert" ] || [ ! -r "$key" ]; then
  echo "ERROR: Native HTTPS is enabled but certificate/key are not readable." >&2
  echo "Expected certificate: $cert" >&2
  echo "Expected private key: $key" >&2
  exit 1
fi

exec gosu makervault gunicorn makervault.wsgi:application \
  --bind 0.0.0.0:8443 \
  --workers "$workers" \
  --timeout "$timeout" \
  --certfile "$cert" \
  --keyfile "$key" \
  --access-logfile - \
  --error-logfile -
