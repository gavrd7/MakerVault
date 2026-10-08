#!/usr/bin/env bash
set -euo pipefail

case "${SYNC_ORCASLICER_PRINTER_CATALOGUE:-true}" in
  true|1|yes|on)
    echo "Background: expanding sparse OrcaSlicer printer catalogue..."
    exec gosu makervault python manage.py sync_orcaslicer_printer_catalogue --best-effort --if-sparse 100
    ;;
  *)
    echo "Background: OrcaSlicer printer catalogue sync disabled."
    ;;
esac
