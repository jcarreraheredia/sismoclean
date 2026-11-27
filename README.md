# sismoclean — Pipeline de Filtrado Digital y Veto Multi-Estación

Entregable WP2 FabLabs – EL-BONGO Physics

sismoclean es un pipeline de procesamiento sísmico diseñado para estaciones Raspberry Shake 4D (estación RE626) operando en entornos con alto nivel de ruido antropogénico. Adquiere señales continuamente por red local vía SeedLink, aplica filtrado digital causal para suprimir ruido instrumental y resonancias mecánicas, detecta arribos mediante STA/LTA y valida cada disparo mediante un esquema de veto multi-estación diferido contra estaciones de referencia FDSN, descartando falsas alarmas locales y clasificando eventos confirmados con PhaseNet.

---

## Información del Proyecto y Autor

- **Autor:** José Fernando Carrera Heredia
- **Programa:** Pregrado en Física
- **Institución:** Universidad San Francisco de Quito (USFQ)
- **Contacto:** jfcarrerah@estud.usfq.edu.ec
- **Repositorio oficial:** https://github.com/jcarreraheredia/sismoclean

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
   - Cascada de Filtros Rechazo de Banda Notch (`deteccion.notch: [29.79, 18.07, 42.24]` Hz, Q = 30): `signal.py` aplica en cascada tres filtros notch IIR de segundo orden para eliminar la resonancia mecánica estructural principal del laboratorio (18.07 Hz) y componentes parásitas de alta frecuencia (29.79 Hz y 42.24 Hz).
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

El contenido se organiza bajo la siguiente estructura modular:

```text
sismoclean/
├── LICENSE                 # Licencia de código abierto MIT
├── README.md               # Este documento de presentación y guía técnica
├── .gitignore              # Reglas de exclusión para control de versiones git
├── data/                   # Muestras de datos experimentales
│   ├── processed/          # Series de tiempo y registros de eventos en formato CSV
│   ├── raw/                # Trazas crudas en formato estándar MiniSEED (.mseed)
│   └── README.md
├── docs/                   # Documentación técnica, manuales y arquitectura
│   ├── ARQUITECTURA_PIPELINE.md
│   └── MANUAL_OPERATIVO.md
├── firmware/               # Documentación del sistema embebido de la estación
│   └── README.md
├── hardware/               # Especificaciones mecánicas, sensores y base de montaje
│   ├── cad_3d/             # Carpeta de reserva para futuros diseños CAD y piezas 3D
│   │   └── README.md
│   └── README.md
├── media/                  # Material visual y gráficos comparativos
│   ├── 01_antes_y_despues_filtrado.png      # Señal y espectro antes vs después del filtro
│   ├── 02_deteccion_evento_sismico.png      # Registro de sismo real y razón STA/LTA
│   ├── 03_discriminacion_ruido_vs_sismo.png # Comparativa de sismo real vs falso disparo
│   └── README.md
├── results/                # Figuras de validación y curvas de rendimiento
│   ├── fig_confirmation.png
│   ├── fig_kept_waveform.png
│   ├── fig_status.png
│   ├── fig_timeline.png
│   ├── fig_veto_waveforms.png
│   └── README.md
└── software/               # Código fuente del pipeline y scripts
    ├── config/             # Archivos de configuración YAML
    │   ├── config.example.yaml
    │   └── config.yaml
    ├── logs/               # Directorio de logs de ejecución (ignorado en git)
    │   └── LEEME.txt
    ├── scripts/            # Diagnóstico de red, medición de retardo y utilidades
    │   ├── diagnostico_red.sh
    │   ├── medir_retardo.py
    │   └── rs_fdsn.py
    ├── src/vivo/           # Módulos Python del pipeline (adquisición, filtros, motor)
    ├── systemd/            # Plantillas para ejecución continua como servicio Linux
    │   ├── vivo-v5.service.in
    │   └── vivo-viewer.service.in
    ├── viewer/             # Aplicación web local (HTML5, JS y CSS)
    ├── install-systemd.sh  # Script de instalación de servicios systemd
    ├── install.sh          # Script de instalación
    ├── requirements.txt    # Lista de dependencias de Python
    └── run.sh              # Lanzador principal del pipeline
```

---

## 4. Guía de Instalación y Puesta en Marcha

### Requisitos Previos
- Sistema Operativo: Linux (Ubuntu 20.04/22.04/24.04 recomendado) o cualquier sistema con Python 3.10 o superior.
- Red: El computador debe encontrarse en la misma red local (LAN) que la Raspberry Shake.

### Paso 1: Clonar el repositorio y entrar al directorio de software
```bash
git clone https://github.com/jcarreraheredia/sismoclean.git
cd sismoclean/software
```

### Paso 2: Crear el entorno virtual e instalar dependencias
```bash
python3 -m venv .venv
source .venv/bin/activate

# Instalar PyTorch CPU desde el repositorio oficial de PyTorch (requerido para resolver torch==2.2.2+cpu)
pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu

# Instalar las dependencias restantes
pip install -r requirements.txt
```

> **Aclaración sobre `install.sh`:** El instalador `./install.sh` está diseñado para paquetes autocontenidos offline que asumen la presencia de carpetas locales `.python/` y `vendor/wheels/`. Al clonar este repositorio desde Git, dichos binarios pesados no están incluidos. Si se ejecuta `install.sh`, este detectará la ausencia del directorio de ruedas e intentará instalar desde Internet, pero fallará al no resolver `torch==2.2.2+cpu` en el índice estándar de PyPI si no se preinstala con `--index-url https://download.pytorch.org/whl/cpu`. Asimismo, el replay offline requiere `tests/fixtures/hour1_*.mseed`, que no se incluyen en este repositorio; en ese caso `install.sh` muestra un AVISO y continúa sin interrumpirse, y puede omitirse con `./install.sh --no-preflight`. Por tanto, se recomienda la instalación manual mediante `venv` + `pip`.

### Paso 3: Configurar la IP del Raspberry Shake
Configure la dirección IP asignada a su estación en la red local:
```bash
./run.sh setup --host 192.168.1.50
```
*(También puede ejecutarse `./run.sh setup` sin argumentos para ingresar interactivamente la IP y puerto).*

### Paso 4: Comprobar la instalación (Preflight)
Valide que las dependencias, configuración y rutas estén operativas:
```bash
./run.sh preflight
```
Opciones:
- `./run.sh preflight --online`: Comprueba adicionalmente la conexión en vivo con SeedLink y FDSN.
- `./run.sh preflight --phase`: Prueba la carga del modelo PhaseNet.
*(Nota: la opción `--replay` requiere trazas de prueba en `tests/fixtures/hour1_*.mseed` que no se incluyen en este repositorio).*

### Paso 5: Probar enlaces de datos
Pruebe la recepción de paquetes en red local (SeedLink, 10 segundos):
```bash
./run.sh lan-check
```
Pruebe la conectividad hacia los servidores FDSN con ventana de retraso (70 min = 4200 s):
```bash
./run.sh fdsn-check
```

### Paso 6: Ejecutar en producción 24/7 (Modo Híbrido)
Inicie el bucle de adquisición continua LAN con confirmación diferida FDSN:
```bash
./run.sh live
```
Banderas opcionales de `./run.sh live`:
- `--duration-min <MIN>`: Detiene el bucle tras los minutos indicados (útil para pruebas).
- `--max-bloques <N>`: Procesa un número límite de bloques de 30 segundos.
- `--no-phasenet`: Desactiva la inferencia de PhaseNet.
- `--fresh`: Borra CSVs y trazas previas antes de comenzar.

### Paso 7: Abrir el Visor Web Local
Inicie el servidor web local para visualizar la señal en tiempo real:
```bash
./run.sh viewer
```
Abra en su navegador: `http://127.0.0.1:8080/`

### Paso 8: Consultar el estado y salud del sistema
En cualquier momento puede consultar el resumen de eventos y métricas de salud:
```bash
./run.sh status
```

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

Este proyecto se distribuye bajo los términos de la Licencia MIT. Para más detalles, consulte el archivo [LICENSE](LICENSE).

Desarrollo realizado en el Departamento de Física de la Universidad San Francisco de Quito (USFQ).

Cualquier consulta sobre la reproducción de este sistema o adaptación a otras estaciones puede dirigirse al autor o consultarse en las guías técnicas dentro de la carpeta `docs/`.
