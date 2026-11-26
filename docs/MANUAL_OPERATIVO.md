# Manual Operativo y Guía de Despliegue

Este documento describe los procedimientos para la instalación, configuración, verificación y ejecución en producción del sistema de monitoreo sísmico.

## 1. Requisitos del Sistema

### Sistema Operativo
- Distribución recomendada: Ubuntu 20.04 LTS, 22.04 LTS o 24.04 LTS (x86_64 o ARM64).
- Espacio en disco: Mínimo 2 GB libres para dependencias y almacenamiento de trazas.
- Memoria RAM: Mínimo 2 GB (recomendado 4 GB para la inferencia de PhaseNet).

### Dependencias del Sistema Base
En entornos basados en Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv chrony netcat-openbsd curl
```

## 2. Instalación del Software

1. Clonar o copiar el repositorio en el equipo host:
```bash
git clone https://gitmilab.redclara.net/el-bongo/wp2fablabs.git
cd sismografo-elbongo/software
```

2. Crear y activar un entorno virtual de Python:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Instalar las dependencias de Python:
```bash
pip install -r requirements.txt
```

Las dependencias principales incluyen `obspy`, `numpy`, `scipy`, `pyyaml`, `pandas`, `requests` y opcionalmente `torch` y `seisbench` si se utiliza el clasificador PhaseNet.

## 3. Configuración de la Red y de la Estación

El archivo de configuración principal se ubica en `software/config/config.yaml`.

### Parámetros Esenciales
```yaml
station:
  name: "RE626"
  fs: 100.0

seedlink:
  host: "192.168.1.50"   # Dirección IP local de la Raspberry Shake
  port: 18000

fdsn:
  timeout: 15.0
  verify_ssl: false      # Requerido debido a la expiración del certificado de data.raspberryshake.org

tiempos:
  bloque_s: 30
  atraso_fdsn_s: 4200    # 70 minutos para compensar latencia de archivo FDSN
  tolerancia_s: 5.0
  solape_s: 2.0
```

### Comprobación de Conectividad
Antes de iniciar el servicio, verifique que el equipo tenga acceso al puerto SeedLink de la estación y a Internet para consultas FDSN:

```bash
bash scripts/diagnostico_red.sh 192.168.1.50
```

Resultado esperado:
- Puerto 18000 externo a Internet: Cerrado o filtrado por firewall institucional (normal).
- Puerto 443 hacia servidores FDSN: Conectividad exitosa.
- Puerto 18000 local hacia la Raspberry Shake: Conexión abierta y operativa.

## 4. Modos de Ejecución

### Modo Simulación / Prueba Offline
Permite validar toda la cadena de filtrado y detección utilizando trazas históricas almacenadas:

```bash
python3 -m vivo.cli --modo sim --sim-tag ev_local_close_M45_20260915
```

### Modo Local (Solo LAN)
Adquiere datos de la estación en tiempo real y ejecuta detección STA/LTA sin consulta a FDSN:

```bash
python3 -m vivo.cli --modo solo-lan --shake-ip 192.168.1.50
```

### Modo Híbrido (Producción 24/7)
Adquiere datos locales en tiempo real, genera alertas provisionales inmediatas y ejecuta el veto multi-estación tras la ventana de 70 minutos:

```bash
python3 -m vivo.cli --modo hibrido --shake-ip 192.168.1.50 --atraso 4200
```

## 5. Visualizador Web Local

Para monitorear las trazas en tiempo real y visualizar los eventos confirmados o vetados, inicie el servidor web interno:

```bash
python3 -m http.server 8080 --directory software/viewer
```

Acceda desde su navegador web en:
`http://127.0.0.1:8080/`

La interfaz incluye:
- Visualización de la señal en tiempo real con Canvas.
- Tabla cronológica de disparos (provisionales, confirmados y vetados).
- Inspección detallada de formas de onda por evento.

## 6. Configuración de Servicio Continuo con systemd

Para garantizar que el pipeline se inicie automáticamente tras reinicios del sistema operativo y continúe ejecutándose sin supervisión:

1. Editar los archivos de servicio ubicados en `software/systemd/`:
   - `vivo-v5.service.in` (pipeline principal)
   - `vivo-viewer.service.in` (servidor web)
2. Ajustar las rutas absolutas según el directorio de instalación.
3. Copiar los archivos a `~/.config/systemd/user/` y habilitar:

```bash
mkdir -p ~/.config/systemd/user
cp software/systemd/vivo-v5.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now vivo-v5.service
```

Para consultar el estado y registros:
```bash
journalctl --user -u vivo-v5.service -f
```
