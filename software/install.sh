#!/usr/bin/env bash
# Instalador offline/online de vivo-v5.
# No necesita sudo para la parte Python.  Para systemd usa install-systemd.sh.
set -euo pipefail
cd "$(dirname "$0")"

WITH_SYSTEMD=0
SKIP_PREFLIGHT=0
for arg in "$@"; do
  case "$arg" in
    --systemd) WITH_SYSTEMD=1 ;;
    --no-preflight) SKIP_PREFLIGHT=1 ;;
    -h|--help)
      echo "Uso: ./install.sh [--systemd] [--no-preflight]"
      exit 0
      ;;
    *) echo "Opción desconocida: $arg"; exit 2 ;;
  esac
done

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
  echo "AVISO: este paquete trae binarios x86_64; esta máquina es $ARCH."
  echo "       Se intentará usar el Python del sistema (modo online)."
fi

if [ -f /etc/os-release ]; then
  . /etc/os-release
  echo "Sistema: ${PRETTY_NAME:-desconocido}"
fi
echo "Arquitectura: $ARCH"

# 1. Python: binario incluido, o Python del sistema como respaldo.
if [ "$ARCH" = "x86_64" ] && [ -x ".python/bin/python3.11" ]; then
  PY_SRC=".python/bin/python3.11"
elif [ "$ARCH" = "x86_64" ] && [ -f "vendor/python.tar.gz" ]; then
  echo "Extrayendo Python 3.11 incluido ..."
  rm -rf .python
  mkdir -p .python
  tar -xzf vendor/python.tar.gz -C .python
  PY_SRC=".python/bin/python3.11"
else
  PY_SRC="$(command -v python3 || true)"
  if [ -z "$PY_SRC" ]; then
    echo "FALLA: no hay Python y el paquete no trae un Python compatible con $ARCH."
    exit 1
  fi
  echo "AVISO: usando Python del sistema: $($PY_SRC --version)"
fi

# 2. Entorno virtual.
if [ ! -x ".venv/bin/python" ]; then
  echo "Creando entorno virtual ..."
  "$PY_SRC" -m venv .venv
fi

# 3. Dependencias: wheelhouse offline si existe, si no online.
if [ "$ARCH" = "x86_64" ] && [ -d "vendor/wheels" ] && [ -n "$(ls -A vendor/wheels 2>/dev/null || true)" ]; then
  echo "Instalando dependencias desde vendor/wheels (sin red) ..."
  .venv/bin/python -m pip install --no-index --find-links vendor/wheels --only-binary=:all: -r requirements.txt
else
  echo "AVISO: sin wheelhouse compatible; instalando desde Internet ..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
fi

chmod +x run.sh install.sh install-systemd.sh 2>/dev/null || true

echo
echo "Comprobación básica ..."
./run.sh preflight || true

if [ "$SKIP_PREFLIGHT" -eq 0 ]; then
  echo
  echo "Prueba offline de detección/veto (puede tardar ~1 minuto) ..."
  if ! ./run.sh --data-dir tests/install_check replay --no-phasenet --fresh; then
    echo "AVISO: el replay no terminó correctamente. Revisa el error anterior."
  fi
fi

if [ "$WITH_SYSTEMD" -eq 1 ]; then
  echo
  ./install-systemd.sh
fi

echo
echo "LISTO."
echo "  1) ./run.sh setup              (poner IP del Shake)"
echo "  2) ./run.sh lan-check"
echo "  3) ./run.sh fdsn-check"
echo "  4) ./run.sh preflight --full"
echo "  5) ./run.sh live --duration-min 3"
echo "  6) ./run.sh viewer             (http://127.0.0.1:8080)"
echo "  7) ./install-systemd.sh        (arranque automático 24/7)"
