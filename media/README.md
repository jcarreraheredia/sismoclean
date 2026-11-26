# Galería Multimedia y Registros Gráficos

Este directorio contiene las representaciones gráficas clave del comportamiento del sistema, la comparación de la señal antes y después del filtrado, y las evidencias de detección sísmica y veto de ruido local.

## 1. Figuras Principales de Monitoreo

### 01_antes_y_despues_filtrado.png
Comparación directa de la señal registrada por la estación RE626:
- Panel superior: Señal cruda de entrada con perturbaciones mecánicas, deriva continua y ruido ambiental.
- Panel medio: Señal tras la cadena de filtrado causal (Paso-Alto 0.7 Hz, Notch sintonizado a 18.07 Hz y Paso-Banda 2.0–20.0 Hz). La relación señal/ruido se incrementa notablemente, destacando las fases sísmicas.
- Panel inferior: Densidad espectral de potencia (PSD vía Welch) donde se evidencia la eliminación de bajas frecuencias parásitas y la atenuación pronunciada de la resonancia de 18.07 Hz.

### 02_deteccion_evento_sismico.png
Registro de detección automática de un sismo regional en la estación RE626:
- Panel superior: Forma de onda filtrada en el canal vertical (EHZ) con el arribo de la onda P señalado en el instante t = 0 s.
- Panel inferior: Evolución temporal continua de la razón STA/LTA (1 s / 20 s), mostrando el cruce del umbral de disparo (3.2) y la ventana de activación del evento.

### 03_discriminacion_ruido_vs_sismo.png
Comparativa fundamental del mecanismo de veto multi-estación:
- Columna izquierda (Sismo Real Confirmado): El evento genera un disparo en RE626 y es registrado de manera coherente en las estaciones de referencia R53D1 (a 6.3 km) y R2A1F (a 1.0 km), clasificándose como KEPT.
- Columna derecha (Ruido Local Vetado): Un transitorio de alta energía (pisada o vibración de laboratorio) activa el detector en RE626, pero las estaciones de referencia permanecen en silencio. El sistema clasifica el evento como VETO y descarta la falsa alarma.

## 2. Esquemas Técnicos y Arquitectura

- `fig_confirmation.png`: Balance estadístico de eventos confirmados mediante el clúster sismológico.
- `fig_timeline.png`: Continuidad temporal de adquisición y control de paquetes en bloques de 30 segundos.
- `fig_status.png`: Distribución porcentual entre eventos vetados (ruido local), pendientes de validación y sismos confirmados.
- `fig_cosmicwatch_hw.png`: Diagrama de instrumentación y flujo de acondicionamiento de señales.
- `fig_munhub_flow.png`: Arquitectura de enlace y consulta de series de datos.

## 3. Registro Fotográfico del Montaje

La estación RE626 utiliza la base y chasis oficial provisto por el fabricante (Raspberry Shake 4D), instalado directamente sobre una superficie rígida de concreto en el laboratorio. En esta carpeta se pueden añadir fotografías de la estación instalada en el sitio para complementar la documentación visual del entregable.
