#!/usr/bin/env bash
set -euo pipefail

# Supervisord runs this separately from HTTP. Keep the three initialisation
# steps sequential to avoid competing writes into the same catalogue tables.
echo "Background: ensuring starter board and component catalogue..."
gosu makervault python manage.py seed_catalogue

echo "Background: ensuring 3D printer catalogue..."
gosu makervault python manage.py seed_printing_catalogue

case "${SYNC_ORCASLICER_PRINTER_CATALOGUE:-true}" in
  true|1|yes|on)
    echo "Background: expanding sparse OrcaSlicer printer catalogue..."
    exec gosu makervault python manage.py sync_orcaslicer_printer_catalogue --best-effort --if-sparse 100
    ;;
  *)
    echo "Background: OrcaSlicer printer catalogue sync disabled."
    ;;
esac
