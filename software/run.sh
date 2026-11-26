#!/usr/bin/env bash
# Ejecuta vivo-v5 con el entorno incluido en el paquete.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x ".python/bin/python3.11" ]; then
  PY=".python/bin/python3.11"
else
  PY="$(command -v python3)"
fi

export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
if [ -d "$PWD/vendor/models" ]; then
  export SEISBENCH_CACHE_ROOT="$PWD/vendor/models"
fi

exec "$PY" -m vivo "$@"
