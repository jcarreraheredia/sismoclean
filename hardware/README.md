# Hardware y Montaje Físico

Este directorio documenta las especificaciones físicas de la estación sismológica, los sensores integrados y las características del montaje mecánico.

## 1. Plataforma de Adquisición: Raspberry Shake 4D (RE626)

La estación opera con el hardware integrado Raspberry Shake 4D acoplado sobre un computador monoplaca Raspberry Pi 3B+.

### Sensores Integrados
- Geófono Vertical (Canal `EHZ`):
  - Frecuencia natural: 4.5 Hz (amortiguamiento nominal ~0.6).
  - Conversor Analógico-Digital: 24 bits.
  - Sensibilidad: Orientada a velocidades débiles del suelo (microtremores y sismos locales/regionales).
- Acelerómetros Triaxiales MEMS (Canales `ENZ`, `ENN`, `ENE`):
  - Rango dinámico: ±2g.
  - Conversor Analógico-Digital: 19 bits.
  - Sensibilidad: Orientada a aceleraciones de movimiento fuerte (evita la saturación del geófono durante eventos cercanos).

### Muestreo y Digitalización
- Tasa de muestreo continua: 100 Hz (100 muestras por segundo) en los 4 canales simultáneos.
- Sincronización temporal: Cliente NTP de alta precisión contra servidores de tiempo en red (desviación < 0.2 s respecto a UTC).

## 2. Chasis y Base de Montaje

Para este despliegue se utiliza la carcasa y base rígida estándar provista de fábrica por Raspberry Shake, sin componentes impresos en 3D adicionales:

- Chasis: Carcasa acrílica transparente con tornillos de fijación mecánica.
- Base de Nivelación: Tres patas regulables de apoyo que permiten un ajuste fino de la horizontalidad.
- Nivel de Burbuja: Integrado en la placa de circuito impreso para calibración visual in situ.
- Anclaje y Aislamiento:
  1. Apoyado sobre suelo macizo de concreto en el laboratorio (eliminando superficies resonantes como escritorios o pisos flotantes).
  2. Eje marcado como "Norte" alineado con el norte geográfico.
  3. Cubierto con domo de aislamiento para mitigar el impacto de corrientes de aire y cambios térmicos repentinos.

## 3. Directorio de Diseños CAD (cad_3d/)

El subdirectorio `cad_3d/` se mantiene reservado como parte de la estructura estandarizada de FabLabs para futuros proyectos o adaptaciones que requieran carcasas personalizadas impresas en 3D, bases magnéticas de acople o cajas de corte láser. Para la estación actual, la base de fábrica satisface los requerimientos de rigidez y desacoplo sísmico.
