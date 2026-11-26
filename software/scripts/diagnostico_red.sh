#!/usr/bin/env bash
# vivo_v3/diagnostico_red.sh — verifica que vivo_v3 puede funcionar sin puerto 18000 externo.
# Uso: bash vivo_v3/diagnostico_red.sh [SHAKE_LAN_IP]
set -u
SHAKE_IP="${1:-rs.local}"
echo "== vivo_v3 diagnostico (Linux) =="
echo "Shake LAN: $SHAKE_IP"
echo
echo "[1] Puerto 18000 EXTERNO (debe FALLAR: firewall U lo bloquea)"
if nc -vz -w 5 data.raspberryshake.org 18000 2>&1; then
  echo "  (!) 18000 externo ABIERTO: podrias usar SeedLink directo (no esperado)"
else
  echo "  OK bloqueado/falla como se esperaba -> vivo_v3 usa 443 en su lugar"
fi
echo
echo "[2] FDSN 443 (debe PASAR)"
curl -k -s -o /dev/null -w "  HTTP %{http_code}\n" \
  "https://data.raspberryshake.org/fdsnws/station/1/query?net=AM&sta=RE626&level=station" \
  || echo "  FAIL 443"
echo
echo "[3] Shake en LAN (debe PASAR: misma red, no cruza firewall)"
if nc -vz -w 3 "$SHAKE_IP" 18000 2>&1; then echo "  OK SeedLink LAN 18000"; else echo "  FAIL LAN 18000: revisa IP/cable/WiFi y SeedLink activado"; fi
if nc -vz -w 3 "$SHAKE_IP" 80 2>&1; then echo "  OK web rs.local:80"; else echo "  FAIL web :80"; fi
echo
echo "[4] Reloj/NTP (veto tolera 5s, ideal <0.2s)"
(timedatectl status 2>/dev/null | head -8) || (chronyc tracking 2>/dev/null | head -8) || echo "  instala chrony: sudo apt install chrony"
echo
echo "[5] Python deps"
python3 -c "import obspy, numpy, scipy, yaml; print('  OK obspy', obspy.__version__)"
echo
echo "Siguiente: python3 vivo_v3/medir_retardo.py --rapido"
