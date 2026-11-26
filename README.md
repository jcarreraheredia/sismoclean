# Estación Sismológica RE626 — Proyecto EL-BONGO (WP2 FabLabs)

Sistema de adquisición continua, filtrado digital causal, detección STA/LTA y discriminación multi-estación para monitoreo sísmico en entornos de laboratorio, desarrollado dentro del paquete de trabajo WP2 (FabLabs) del proyecto EL-BONGO Physics.

---

## Información del Proyecto y Autor

- **Autor:** José Fernando Carrera Heredia
- **Programa:** Pregrado en Física
- **Institución:** Universidad San Francisco de Quito (USFQ)
- **Contacto:** jfcarrerah@estud.usfq.edu.ec
- **Consorcio:** EL-BONGO Physics — WP2 FabLabs
- **Repositorio de consolidación:** https://gitmilab.redclara.net/el-bongo/wp2fablabs

---

## 1. Propósito y Descripción General

El propósito principal de este desarrollo es implementar una estación sísmica basada en instrumentación abierta capaz de operar de manera confiable en entornos con alto nivel de ruido antropogénico (vibraciones por pisadas, tráfico vehicular o equipos de laboratorio). En una estación aislada, estas perturbaciones mecánicas generan continuas falsas alarmas que saturan los registros.

Para resolver este problema sin recurrir a costosas infraestructuras dedicadas, este sistema combina:
- Una estación **Raspberry Shake 4D** (código de red internacional: `RE626`) ubicada en Cumbayá (USFQ).
- Un canal de velocidad vertical de 24 bits (`EHZ`, geófono 4.5 Hz) y tres canales ortogonales de aceleración de 19 bits (`ENZ`, `ENN`, `ENE`, acelerómetro MEMS ±2g).
- Una cadena de **filtrado digital causal** que elimina la deriva instrumental y resonancias mecánicas locales sin distorsionar el tiempo de arribo de las fases sísmicas.
- Detección automática de arribos mediante el algoritmo de razón **STA/LTA** (Short-Term Average / Long-Term Average).
- Un mecanismo de **veto multi-estación diferido** que consulta estaciones de referencia cercanas mediante servidores FDSN para comprobar si una perturbación fue observada en múltiples sensores (sismo real) o solo en la estación local (ruido descartado).
- Clasificación de fases con el modelo de aprendizaje profundo **PhaseNet**.
- Visualización interactiva en tiempo real mediante un visor web local ligero basado en HTML5 y Canvas.

---

## 2. Cómo Funciona el Sistema

El procesamiento de señales sigue un ciclo continuo compuesto por las siguientes etapas:

1. **Adquisición local por SeedLink (puerto 18000 en LAN):**
   La estación RE626 transmite paquetes MiniSEED a 100 Hz dentro de la red local. Esto permite recolectar los datos sin requerir que la estación abra puertos externos hacia internet, adaptándose a las políticas estrictas de los cortafuegos universitarios.

2. **Acondicionamiento y filtrado causal:**
   Cada bloque de señal (30 segundos) pasa por:
   - Filtro Paso-Alto (0.7 Hz, Butterworth orden 2): suprime la deriva de continua (offset DC).
   - Filtro Rechazo de Banda Notch (18.07 Hz, Q = 30): elimina una vibración mecánica resonante propia del edificio del laboratorio.
   - Filtro Paso-Banda (2.0 a 20.0 Hz, Butterworth orden 4): concentra la energía en el rango típico de sismos locales y regionales.

3. **Detección STA/LTA (onda P en canal EHZ):**
   Se calcula la razón entre la energía en una ventana corta (STA = 1.0 s) y una ventana larga (LTA = 20.0 s). Si la razón supera el umbral de activación (3.2), se emite una alerta provisional inmediata con su marca de tiempo UTC.

4. **Confirmación y veto diferido (70 minutos):**
   Los servidores globales de Raspberry Shake tardan aproximadamente 60 minutos en consolidar y archivar los datos de estaciones públicas en sus servidores FDSN. Por ello, el pipeline agenda una consulta automática a los 70 minutos para descargar las trazas de las estaciones de referencia configuradas:
   - **Evento confirmado (KEPT):** Si la perturbación fue registrada simultáneamente en una o más estaciones vecinas dentro de una ventana de viaje de onda compatible (tolerancia de ±5 s), se confirma como sismo real.
   - **Evento vetado (VETO):** Si la perturbación solo existió en RE626 y las vecinas permanecieron en silencio, se marca como ruido local y se descarta (el sistema logra descartar más del 80 % de las falsas alarmas).

5. **Picking de fases con PhaseNet:**
   Sobre los eventos confirmados, el modelo PhaseNet analiza las tres componentes ortogonales para calcular con precisión los tiempos de arribo de la onda P y de la onda S.

6. **Despliegue en el Visor Web:**
   Los datos se almacenan en archivos CSV estructurados y se sirven localmente mediante una interfaz gráfica Canvas en el navegador web.

---

## 3. Estructura del Repositorio

El contenido cumple con la nomenclatura estandarizada por el proyecto EL-BONGO Physics:

```text
sismografo-elbongo/
├── README.md               # Este documento de presentación y guía técnica
├── .gitignore              # Reglas de exclusión para control de versiones git
├── docs/                   # Documentación técnica, manuales y poster científico
│   ├── ARQUITECTURA_PIPELINE.md
│   ├── MANUAL_OPERATIVO.md
│   └── poster_cientifico_sismografo.pdf
├── data/                   # Muestras de datos experimentales
│   ├── raw/                # Trazas crudas en formato estándar MiniSEED (.mseed)
│   ├── processed/          # Series de tiempo y registros de eventos en formato CSV
│   └── README.md
├── software/               # Código fuente del pipeline y scripts
│   ├── src/vivo/           # Módulos Python del pipeline (adquisición, filtros, motor)
│   ├── scripts/            # Diagnóstico de red, medición de retardo y utilidades
│   ├── viewer/             # Aplicación web local (HTML5, JS y CSS)
│   ├── config/             # Archivos de configuración YAML
│   ├── systemd/            # Plantillas para ejecución continua como servicio Linux
│   └── requirements.txt    # Lista de dependencias de Python
├── firmware/               # Documentación del sistema embebido de la estación
│   └── README.md
├── hardware/               # Especificaciones mecánicas, sensores y base de montaje
│   ├── README.md
│   └── cad_3d/             # Carpeta de reserva para futuros diseños CAD y piezas 3D
├── results/                # Figuras de validación, curvas de rendimiento y póster
│   ├── fig_kept_waveform.png
│   ├── fig_veto_waveforms.png
│   ├── fig_timeline.png
│   ├── fig_confirmation.png
│   ├── fig_status.png
│   └── README.md
└── media/                  # Material visual y gráficos comparativos
    ├── 01_antes_y_despues_filtrado.png      # Señal y espectro antes vs después del filtro
    ├── 02_deteccion_evento_sismico.png      # Registro de sismo real y razón STA/LTA
    ├── 03_discriminacion_ruido_vs_sismo.png # Comparativa de sismo real vs falso disparo
    └── README.md
```

---

## 4. Guía de Instalación y Puesta en Marcha

### Requisitos Previos
- Sistema Operativo: Linux (Ubuntu 20.04/22.04/24.04 recomendado) o cualquier sistema con Python 3.10 o superior.
- Red: El computador debe encontrarse en la misma red local (LAN) que la Raspberry Shake.

### Paso 1: Clonar el repositorio y entrar al directorio de software
```bash
git clone https://gitmilab.redclara.net/el-bongo/wp2fablabs.git
cd sismografo-elbongo/software
```

### Paso 2: Crear el entorno virtual e instalar dependencias
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Paso 3: Diagnosticar la conectividad de red
Ejecute el script de diagnóstico indicando la IP de su Raspberry Shake:
```bash
bash scripts/diagnostico_red.sh 192.168.1.50
```
El diagnóstico confirmará si el puerto SeedLink local (18000) responde y si hay salida HTTPS (puerto 443) hacia los servidores FDSN.

### Paso 4: Configurar los parámetros de la estación
Abra el archivo `software/config/config.yaml` y asigne la IP de su estación en la sección `seedlink`:
```yaml
seedlink:
  host: "192.168.1.50"   # Cambiar por la IP real o nombre rs.local de su Shake
  port: 18000
```

### Paso 5: Ejecutar una prueba offline de validación
Para verificar que el filtrado y detección funcionan correctamente sin necesidad del sensor activo:
```bash
python3 -m vivo.cli --modo sim --sim-tag ev_local_close_M45_20260915
```

### Paso 6: Ejecutar en producción (24/7)
Para arrancar el monitoreo continuo con confirmación multi-estación:
```bash
python3 -m vivo.cli --modo hibrido --shake-ip 192.168.1.50 --atraso 4200
```

### Paso 7: Abrir el Visor Web
En una terminal separada, inicie el visualizador:
```bash
python3 -m http.server 8080 --directory viewer
```
Abra en su navegador: `http://127.0.0.1:8080`

---

## 5. Cómo Cambiar las Estaciones de Referencia para el Veto Sísmico

El sistema utiliza un clúster de estaciones cercanas para contrastar cada disparo y determinar si se trata de un sismo regional o ruido local. Todos los ajustes del clúster se realizan dentro del archivo **`software/config/config.yaml`**.

### 5.1. ¿Cómo seleccionar estaciones adecuadas?
1. Ingrese a la plataforma pública de mapa: https://stationview.raspberryshake.org/
2. Ubique la posición geográfica de su estación principal (`RE626`).
3. Identifique estaciones cercanas con buen nivel de servicio y bajo nivel de ruido. En nuestro entorno se seleccionaron:
   - `R2A1F` (a aproximadamente 1.0 km de distancia).
   - `R53D1` (a aproximadamente 6.3 km de distancia).
4. Anote el código de red (normalmente `AM`) y el código de estación de 5 caracteres.

### 5.2. Edición del archivo `config.yaml`

Para cambiar, agregar o remover estaciones de referencia, modifique las siguientes secciones del archivo:

#### A. Definición de las estaciones del clúster
En la clave `cluster:`, liste las estaciones que el sistema debe consultar por FDSN:
```yaml
cluster:
  - {network: "AM", station: "R2A1F", location: "00"}
  - {network: "AM", station: "R53D1", location: "00"}
  # Para agregar una tercera estación:
  # - {network: "AM", station: "RNUEVA", location: "00"}
```

#### B. Ajuste de los umbrales de detección STA/LTA por estación
Cada estación sismológica posee condiciones de ruido ambiental particulares. En la sección `deteccion.umbrales:` se calibran los límites de disparo (`on`) y apagado (`off`) para cada estación individual:
```yaml
deteccion:
  umbrales:
    RE626: {on: 3.2, off: 1.4}   # Estación local (laboratorio)
    R2A1F: {on: 2.8, off: 1.2}   # Estación de referencia 1
    R53D1: {on: 3.5, off: 1.5}   # Estación de referencia 2
    # RNUEVA: {on: 3.0, off: 1.5}
```
- Si una estación vecina es muy silenciosa, se puede usar un umbral más bajo (e.g. `2.8`).
- Si una estación vecina tiene ruido de fondo, se recomienda subir el umbral (e.g. `3.5`) para evitar falsas confirmaciones.

#### C. Tolerancia temporal y solape
En la misma sección `deteccion:` se define la ventana temporal permitida para que las ondas viajen entre las estaciones:
```yaml
deteccion:
  tol_onset_s: 5.0     # Tolerancia máxima en segundos para el tiempo de arribo
  pad_solape_s: 2.0    # Margen de solape temporal entre trazas
```
Si añade estaciones situadas a mayor distancia (por ejemplo, a más de 30 km), incremente `tol_onset_s` (por ejemplo, a 10.0 s o 15.0 s) para permitir el tiempo de propagación de la onda sísmica regional.

#### D. Estaciones evaluadas por PhaseNet
Para indicar cuáles estaciones deben ser procesadas por el modelo de picking de fases:
```yaml
phasenet:
  compare_stations: ["R53D1"]  # Estación limpia de referencia para contrastar picks
```

---

## 6. Resultados y Rendimiento Demostrado

- **Efectividad en el filtrado de ruido (tasa de veto):** Durante periodos de prueba y auditoría, el sistema descartó exitosamente el **80.2 %** de los disparos provisionales generados por actividad humana local en el laboratorio.
- **Detección de eventos reales:** Los sismos tectónicos fueron confirmados de manera cruzada por las estaciones de referencia con una dispersión de arribo menor a 0.2 segundos.
- **Autonomía y robustez:** Al almacenar las trazas directamente en formato CSV y archivos planos rotados, el sistema evita fallos por corrupción de bases de datos y funciona indefinidamente sin supervisión humana.

---

## 7. Licencia y Créditos

Este trabajo forma parte de los entregables de desarrollo e instrumentación científica del proyecto **EL-BONGO Physics (WP2 FabLabs)**.

Cualquier consulta sobre la reproducción de este sistema o adaptación a otras estaciones puede dirigirse al autor o consultarse en las guías técnicas dentro de la carpeta `docs/`.
