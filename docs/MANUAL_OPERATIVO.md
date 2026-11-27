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
git clone https://github.com/jcarreraheredia/sismoclean.git
cd sismoclean/software
```

2. Crear y activar un entorno virtual de Python:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Instalar las dependencias de Python:
La rueda de `torch==2.2.2+cpu` no está alojada directamente en el índice estándar de PyPI, por lo que debe instalarse indicando el repositorio de PyTorch antes del archivo de requerimientos:
```bash
pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

> **Nota sobre `install.sh`:** El script `install.sh` está diseñado para paquetes autocontenidos offline que asumen carpetas locales (`vendor/wheels/` y `.python/`). Al clonar este repositorio desde Git, dichos binarios pesados no están incluidos. Si se ejecuta `install.sh`, este detectará la ausencia del wheelhouse e intentará instalar dependencias desde Internet, pero la descarga directa de `torch==2.2.2+cpu` fallará en PyPI sin la bandera `--index-url` indicada arriba, y la prueba final de replay requerirá fixtures no incluidas. Por ello, se recomienda la instalación manual con `venv` y `pip`.

## 3. Configuración de la Red y de la Estación

El archivo de configuración principal se ubica en `software/config/config.yaml`. También puede configurarse interactivamente o mediante banderas ejecutando `./run.sh setup --host <IP_DEL_SHAKE>`.

### Parámetros Esenciales
```yaml
station:
  network: "AM"
  station: "RE626"
  location: "00"
  channels: ["EHZ", "ENE", "ENN", "ENZ"]
  fs: 100.0

seedlink:
  host: "192.168.1.50"   # Dirección IP local de la Raspberry Shake (o rs.local)
  port: 18000
  timeout_s: 20

fdsn:
  base: "https://data.raspberryshake.org/fdsnws"
  verify_ssl: false      # Requerido debido a la expiración del certificado TLS de data.raspberryshake.org
  timeout_s: 60
  retries: 4

tiempos:
  bloque_s: 30
  margen_s: 30
  atraso_fdsn_s: 4200    # 70 minutos para compensar latencia de archivo FDSN
  poll_confirm_s: 60

deteccion:
  tol_onset_s: 5.0      # Tolerancia de tiempo de arribo para veto multi-estación
  pad_solape_s: 2.0     # Margen de solape temporal entre trazas
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

Todos los subcomandos se ejecutan a través de `./run.sh`, el cual configura automáticamente el entorno de ejecución y `PYTHONPATH`.

### Configuración de la IP de la estación
Establece la IP de la estación en `config/config.yaml`:
```bash
./run.sh setup --host 192.168.1.50
```

### Comprobación de dependencias (Preflight)
Verifica que las librerías, configuración y rutas estén listas:
```bash
./run.sh preflight
```
Opciones adicionales:
- `./run.sh preflight --online`: Comprueba adicionalmente la conectividad activa hacia SeedLink y FDSN.
- `./run.sh preflight --phase`: Evalúa la carga del modelo PhaseNet con un evento de prueba.

### Diagnóstico de enlace local SeedLink
Captura paquetes durante 10 segundos para verificar la recepción de los 4 canales:
```bash
./run.sh lan-check
# Opcional: especificar duración en segundos
./run.sh lan-check --seconds 15
```

### Diagnóstico de consultas FDSN
Descarga trazas de archivo con la ventana de retraso configurada (70 minutos por defecto):
```bash
./run.sh fdsn-check
# Opcional: especificar retraso en segundos
./run.sh fdsn-check --atraso 4200
```

### Monitoreo continuo 24/7 (Modo Híbrido en Producción)
Inicia el bucle de adquisición continua LAN con confirmación multi-estación diferida por FDSN:
```bash
./run.sh live
```
Banderas opcionales de `./run.sh live`:
- `--duration-min <MIN>`: Detiene la ejecución tras un número determinado de minutos (útil para pruebas controladas).
- `--max-bloques <N>`: Procesa un número máximo de bloques de 30 segundos y finaliza.
- `--no-phasenet`: Desactiva la inferencia de PhaseNet en CPU.
- `--fresh`: Limpia los archivos CSV y trazas generadas antes de arrancar.

### Consulta de estado y salud
Muestra el conteo de eventos (confirmados, vetados, pendientes), métricas de salud y los últimos eventos registrados:
```bash
./run.sh status
# Opcional: especificar cuántos eventos mostrar
./run.sh status --last 15
```

> **Nota sobre el subcomando `replay` (Prueba offline):** El subcomando `./run.sh replay` está programado para reproducir el benchmark offline `hour1` (60 disparos / 25 confirmados sin red). Sin embargo, requiere las trazas históricas `tests/fixtures/hour1_*.mseed` que no están incluidas en este repositorio. Para validar la instalación en este entorno use `./run.sh preflight`.

## 5. Visualizador Web Local

Inicia el servidor web local con control de caché:

```bash
./run.sh viewer
# Opcional: cambiar puerto o interfaz de red
./run.sh viewer --port 8080 --host 127.0.0.1
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
