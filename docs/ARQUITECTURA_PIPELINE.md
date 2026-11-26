# Arquitectura del Pipeline Sísmico

Este documento detalla el diseño técnico y el flujo de procesamiento de señales del sistema de monitoreo sísmico para la estación RE626 (Raspberry Shake 4D), desarrollado en la Universidad San Francisco de Quito (USFQ).

## 1. Vision General del Sistema

El objetivo principal del pipeline es detectar eventos sismicos reales y filtrar eficazmente el ruido antropogenico local (trafico vehicular, maquinaria de laboratorio, actividad peatonal), operando de manera continua las 24 horas del dia, los 7 dias de la semana.

El sistema se compone de cinco etapas fundamentales:

1. Adquisicion continua en red local (LAN) mediante el protocolo SeedLink.
2. Filtrado digital causal en tiempo real.
3. Deteccion de disparos mediante el algoritmo STA/LTA (onda primaria P).
4. Confirmacion y veto multi-estacion a traves de consultas FDSN.
5. Clasificacion y seleccion de fase (phase picking) con redes neuronales (PhaseNet).

```
   [Estacion RE626 (LAN)]
             │
             ▼
   [Adquisicion SeedLink (puerto 18000)]
             │
             ▼ (Bloques de 30 s)
   [Filtrado Digital Causal]
   - High-Pass (0.7 Hz)
   - Notch IIR (18.07 Hz, Q=30)
   - Band-Pass (2.0 - 20.0 Hz)
             │
             ▼
   [Detector STA/LTA (Canal EHZ)]
             │
      ┌──────┴────────────────────────┐
      ▼                               ▼
[Sin disparo]                 [Disparo Detectado]
 (Descarte)                    (Registro Provisional)
                                      │
                                      ▼
                        [Espera de latencia FDSN (70 min)]
                                      │
                                      ▼
                        [Consulta Multi-estacion FDSN]
                        - Estacion R2A1F (1.0 km)
                        - Estacion R53D1 (6.3 km)
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                 [Coincidencia >= 1]       [Sin Coincidencia]
                         │                         │
                         ▼                         ▼
                  [Evento Confirmado]        [Veto de Ruido Local]
                  (Estado: KEPT)            (Estado: VETO)
                         │
                         ▼
                  [Analisis PhaseNet]
                  - Canal 3C / EHZ
                  - Picking de ondas P y S
                         │
                         ▼
                  [Persistencia en CSV y Visor Web]
```

## 2. Adquisicion de Senales

- Protocolo: SeedLink (TCP puerto 18000 en la red de area local).
- Canales monitoreados:
  - EHZ: Geofono vertical de alta sensibilidad (velocidad, m/s).
  - ENZ, ENN, ENE: Acelerometros triaxiales MEMS (aceleracion, m/s2).
- Frecuencia de muestreo: 100 muestras por segundo (100 Hz).
- Procesamiento en bloques: Segmentos de 30 segundos de duracion para equilibrar la latencia de deteccion con el rendimiento computacional.

## 3. Cadena de Filtrado Digital

Para preservar la causalidad temporal y evitar precursores artificiales previos al arribo de ondas sismicas, todo el filtrado en la etapa de deteccion se ejecuta de forma causal (IIR / SOS):

1. Filtro Paso-Alto (High-Pass):
   - Frecuencia de corte: 0.7 Hz.
   - Tipo: Butterworth orden 2.
   - Proposito: Eliminar la deriva de continua (offset DC) y tendencias de baja frecuencia.

2. Filtro Rechazo de Banda (Notch IIR):
   - Frecuencia central: 18.07 Hz.
   - Factor de calidad: Q = 30 (ancho de banda aproximado de 0.60 Hz).
   - Proposito: Suprimir una linea de vibracion mecanica persistente propia del entorno de instalacion.

3. Filtro Paso-Banda (Band-Pass):
   - Rango de frecuencias: 2.0 Hz a 20.0 Hz.
   - Tipo: Butterworth orden 4.
   - Proposito: Aislar el espectro tipico de sismos locales y regionales, eliminando ruido de alta frecuencia.

## 4. Algoritmo de Deteccion (STA/LTA)

Se utiliza el metodo de razon entre el promedio de corto plazo y el promedio de largo plazo (Classic STA/LTA):

- Longitud de ventana corta (STA): 1.0 segundo.
- Longitud de ventana larga (LTA): 20.0 segundos.
- Umbral de disparo (Trigger On): 3.2.
- Umbral de apagado (Trigger Off): 1.4.

Cuando la razon STA/LTA supera el umbral de disparo, se genera un evento con marca de tiempo UTC exacta y se almacena en estado provisional.

## 5. Veto Multi-Estacion mediante FDSN

Debido a que el laboratorio presenta perturbaciones locales frecuentes, una estacion aislada generaria multiples falsas alarmas. El sistema implementa un esquema de veto cruzado con estaciones sismicas de referencia cercanas:

- Estacion R2A1F: Ubicada a aproximadamente 1.0 km.
- Estacion R53D1: Ubicada a aproximadamente 6.3 km.

### Mecanica del Veto
1. Las estaciones de referencia publican sus datos a traves de servidores FDSN con un retraso habitual de aproximadamente 60 a 70 minutos.
2. El sistema programa una comprobacion automatica 70 minutos despues de cada deteccion provisional en RE626.
3. Se descargan las trazas de las estaciones de referencia para la misma ventana temporal (con una tolerancia de tiempo de arribo de ±5 segundos y solape de ±2 segundos).
4. Criterio de clasificacion:
   - KEPT (Confirmado): El disparo fue registrado simultaneamente en al menos una de las estaciones de referencia dentro de la ventana de viaje de onda esperada.
   - VETO (Descartado): La senal fue observada unicamente en RE626, indicando ruido antropogenico local o impacto directo sobre la estructura del laboratorio.

## 6. Clasificacion de Fases con PhaseNet

Sobre los eventos clasificados como confirmados (KEPT), se ejecuta el modelo de aprendizaje profundo PhaseNet (Zhu & Beroza, 2019) optimizado para CPU:

- Entrada: Senales triaxiales (ENZ, ENN, ENE) o canal vertical triplicado si los canales horizontales presentan baja relacion senal/ruido.
- Preprocesamiento PhaseNet: Filtro paso-banda de 1.0 a 45.0 Hz con correccion de fase cero.
- Salida: Probabilidades de arribo de ondas compresionales (P) y ondas de cizalla (S).
- Umbral de aceptacion: Probabilidad minima de 0.15.

## 7. Persistencia y Visualizacion

- Almacenamiento: Archivos planos en formato CSV rotados periodicamente. Este enfoque elimina la dependencia de motores de base de datos externos o servicios en la nube, garantizando operacion autonoma.
- Interfaz de usuario: Servidor web ligero en Python que sirve una interfaz HTML5/Canvas interactiva, accesible localmente en el puerto 8080.
