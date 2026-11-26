# Estructura y Formato de Datos

Este directorio contiene muestras representativas de datos sismológicos adquiridos por la estación RE626 y las estaciones de referencia del clúster sismológico.

## 1. Organización del Directorio

- `raw/`: Archivos de ondas en formato estándar MiniSEED (`.mseed`) sin procesar, tal como son emitidos por el digitalizador de la Raspberry Shake 4D.
- `processed/`: Archivos tabulares en formato CSV generados por el pipeline tras aplicar calibración, filtrado y detección STA/LTA.

## 2. Datos Crudos (raw/)

- `RE626_test.mseed`: Registro sismológico continuo de 4 canales capturado por la estación RE626:
  - Canal `EHZ`: Geófono vertical (100 Hz, velocidad del suelo en unidades de cuentas digitales / m/s).
  - Canales `ENZ`, `ENN`, `ENE`: Acelerómetros triaxiales MEMS (100 Hz, aceleración del suelo en unidades de cuentas digitales / m/s²).

Los archivos MiniSEED pueden ser leídos e inspeccionados directamente utilizando la biblioteca ObsPy en Python o paquetes como SeisComP y SAC.

## 3. Datos Procesados (processed/)

Los archivos CSV contienen métricas temporales y espectrales calculadas por el pipeline:

### live.csv
Monitoreo continuo de las señales en bloques de 30 segundos:
- `timestamp_utc`: Marca de tiempo en formato ISO 8601 UTC.
- `rms_ehz`: Valor cuadrático medio (RMS) del canal vertical filtrado.
- `pico_ehz`: Amplitud máxima registrada en el bloque.
- `sta_lta_max`: Razón STA/LTA máxima observada en el intervalo.

### bloques.csv
Resumen por bloque procesado que documenta el estado de la conexión, continuidad temporal de los paquetes de datos y posibles brechas (gaps).

### Archivos de Eventos Individuales
Archivos con el patrón `RE626_<TIMESTAMP>_<ESTACION>.csv`:
Contienen la serie temporal de 60 segundos centrada en el instante del disparo detectado, permitiendo contrastar la traza de la estación local (`RE626`) con las estaciones de referencia (`R2A1F`, `R53D1`) para la auditoría de veto multi-estación.

Campos incluidos:
- `time_offset_s`: Tiempo relativo en segundos con respecto al disparo.
- `raw_counts`: Amplitud sin filtrar en cuentas digitales.
- `filtered_velocity`: Velocidad del suelo filtrada (µm/s).
- `sta_lta`: Serie temporal de la razón STA/LTA calculada.
