#!/usr/bin/env bash
set -euo pipefail

mode="${MAKERVAULT_HTTPS_ENABLED:-auto}"
cert="${MAKERVAULT_TLS_CERT_FILE:-/app/tls/cert.pem}"
key="${MAKERVAULT_TLS_KEY_FILE:-/app/tls/key.pem}"
workers="${HTTPS_WEB_CONCURRENCY:-1}"
timeout="${GUNICORN_TIMEOUT:-120}"

case "${mode,,}" in
  0|false|no|off)
    echo "Native HTTPS listener disabled."
    exec sleep infinity
    ;;
  auto)
    echo "Native HTTPS auto mode: waiting for a certificate in TLS storage."
    while [ ! -r "$cert" ] || [ ! -r "$key" ]; do sleep 3; done
    ;;
  1|true|yes|on)
    if [ ! -r "$cert" ] || [ ! -r "$key" ]; then
      echo "ERROR: Native HTTPS is explicitly enabled but certificate/key are not readable." >&2
      exit 1
    fi
    ;;
  *)
    echo "ERROR: MAKERVAULT_HTTPS_ENABLED must be auto, true or false." >&2
    exit 1
    ;;
esac

echo "Starting MakerVault native HTTPS listener on 8443."
exec gosu makervault gunicorn makervault.wsgi:application \
  --bind 0.0.0.0:8443 \
  --workers "$workers" \
  --timeout "$timeout" \
  --certfile "$cert" \
  --keyfile "$key" \
  --access-logfile - \
  --error-logfile -
