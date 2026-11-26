# Firmware y Sistemas Embebidos

Este documento describe el estado del firmware y software embebido de la estación sismológica.

## 1. Sistema Embebido Principal

La estación no requiere microcontroladores externos (como Arduino, ESP32 o FPGA) para la adquisición sísmica primaria. Toda la digitalización, sincronización y transmisión es gestionada por la electrónica dedicada de la placa Raspberry Shake 4D:

- Sistema Operativo Embebido: Raspberry Shake OS (distribución Linux basada en Debian).
- Servidor de Adquisición: Daemon SeedLink nativo corriendo sobre el puerto local TCP 18000.
- Conversión y Calibración: La placa cuenta con convertidores ADC dedicados (24 bits para el geófono y 19 bits para los acelerómetros) calibrados de fábrica.
- Sincronización de Tiempo: Demonio NTP integrado que sincroniza el reloj del sistema mediante conexión Ethernet/Wi-Fi.

## 2. Configuración del Servicio SeedLink

Para que el software del pipeline pueda conectarse desde el computador de procesamiento, el servicio SeedLink debe estar activo en la estación:

1. Acceder a la interfaz web de la Raspberry Shake (`http://rs.local` o la IP de la estación).
2. Dirigirse a `Settings` -> `Data`.
3. Verificar que la opción `SeedLink Server` esté habilitada (`ON`).
4. El puerto de escucha estándar en la red local es `18000`.

La transmisión se realiza en formato MiniSEED en bloques de baja latencia sin necesidad de firmware compilado externamente.
