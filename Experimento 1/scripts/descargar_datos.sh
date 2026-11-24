#!/usr/bin/env bash
set -euo pipefail
SCRIPTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPTS/cargar_datos.py" descargar "$@"
