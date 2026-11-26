# Resultados Experimentales y Métricas de Rendimiento

Este directorio reúne las figuras científicas, estadísticas operativas y resultados del proceso de validación del sistema sismológico de la estación RE626.

## 1. Figuras Principales

### fig_kept_waveform.png
Muestra la forma de onda de un sismo regional confirmado (evento clasificado como KEPT).
- El arribo de la onda P y las fases posteriores se identifican con claridad tanto en la estación RE626 como en las estaciones de referencia R2A1F (a 1.0 km) y R53D1 (a 6.3 km).
- La correlación temporal entre las tres estaciones confirma el origen tectónico del evento.

### fig_veto_waveforms.png
Muestra un ejemplo representativo de falso disparo generado por ruido antropogénico local (evento clasificado como VETO).
- Se observa un transitorio de alta energía en la estación RE626 (origen mecánico o vibración en el edificio).
- Las estaciones de referencia R2A1F y R53D1 permanecen en niveles basales de ruido, demostrando que la perturbación fue puramente local y justificando su descarte automático.

### fig_confirmation.png
Esquema de decisión y flujo estadístico del sistema de confirmación y veto diferido (70 minutos).

### fig_timeline.png
Diagrama de cobertura temporal que ilustra la continuidad de la adquisición en bloques de 30 segundos, el seguimiento de la latencia de llegada de paquetes y la resolución de brechas temporales.

### fig_status.png
Distribución de estados del conjunto de alertas auditadas:
- Disparos provisionales totales.
- Proporción de eventos vetados por monostación (ruido local).
- Proporción de eventos confirmados por coincidencia multi-estación.

### poster_v7_1.png
Versión gráfica completa del póster científico presentado para el proyecto, detallando la instrumentación, modelos físicos y validación estadística.

## 2. Métricas Clave de Desempeño

Durante las sesiones de auditoría y prueba continua del pipeline:
- Tasa de rechazo de ruido local (tasa de veto): 80.2 % de los disparos provisionales fueron descartados correctamente por no tener correlación en las estaciones vecinas.
- Cobertura de adquisición: 88.0 % a 99.5 % de disponibilidad de paquetes de datos en periodos estables.
- Falsas alarmas confirmadas: Cero falsos positivos multi-estación registrados durante ventanas de control nocturno.
