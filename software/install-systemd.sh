#!/usr/bin/env bash
# Instala y arranca los dos servicios systemd.  Necesita sudo.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
USER_NAME="${SUDO_USER:-$USER}"

if [ ! -x ".venv/bin/python" ]; then
  echo "FALLA: primero ejecuta ./install.sh"
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "Instalando servicios para el usuario $USER_NAME en $DIR ..."
mkdir -p viewer/data/trazas viewer/data/trazas_raw logs

for unit in vivo-v5.service vivo-viewer.service; do
  tmp="$(mktemp)"
  sed -e "s|@DIR@|$DIR|g" -e "s|@USER@|$USER_NAME|g" "systemd/$unit.in" > "$tmp"
  $SUDO cp "$tmp" "/etc/systemd/system/$unit"
  rm -f "$tmp"
done

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now vivo-v5.service
$SUDO systemctl enable --now vivo-viewer.service

echo
$SUDO systemctl --no-pager --full status vivo-v5.service || true
echo
echo "Visor local: http://127.0.0.1:8080/"
echo "Desde otro PC: ssh -L 8080:127.0.0.1:8080 $USER_NAME@IP_DE_ESTE_PC"
echo
echo "Logs:  journalctl -u vivo-v5 -f"
echo "       journalctl -u vivo-viewer -f"
