# Nombre de la etapa: Control secuencial de bombas de diafragma con ESP32, MicroPython, MQTT y Node‑RED

## Integrantes
- [David Santiago Puentes Cárdenas — 99225](https://github.com/Monstertrox)  
- [Juan David Arias Bojacá — 107394](https://github.com/juandariasb-ai)


## Documentación

## Objetivo del sistema

El objetivo es automatizar cinco bombas de diafragma conectadas a una ESP32 utilizando MicroPython. Cada bomba se activa únicamente cuando recibe dos señales lógicas por MQTT:

- **galga = 1**: indica que hay pintura disponible (presión o nivel correcto).
- **temp_ok = 1**: indica que la temperatura medida para esa bomba está dentro de un rango seguro (22 – 28 °C). El procesamiento del valor de temperatura se realiza fuera de la ESP32; aquí solo se recibe 0 o 1.

La ESP32 recorre las bombas de forma secuencial y activa cada una durante un tiempo predeterminado sólo si ambas señales son 1. Además, la placa publica un mensaje de estado cada vez que enciende o apaga una bomba y utiliza un LED indicativo para mostrar que hay una bomba funcionando.

## Flujo completo del sistema

1. **Sensado y lógica previa** (por ejemplo, en Node‑RED o un microcontrolador auxiliar): se miden los niveles de pintura y la temperatura de cada línea y se generan señales lógicas (0/1) para galga y temp_ok de cada bomba.
   - Esta lógica publica un JSON con dichas señales en el topic MQTT `linea/pintura/cmd`.

2. La **ESP32** se conecta al Wi‑Fi, se suscribe al topic de comandos (`linea/pintura/cmd`) y queda a la espera de mensajes. Cuando recibe un JSON válido actualiza sus variables internas.

3. La **ESP32** recorre las 5 bombas en orden; al encontrar una combinación galga = 1 y temp_ok = 1 enciende esa bomba durante un tiempo fijo, enciende un LED de estado y publica un mensaje en el topic `linea/pintura/status` indicando que la bomba se ha encendido. Tras el tiempo de funcionamiento, apaga la bomba, apaga el LED y publica un mensaje indicando que se apagó.

4. Si no llegan mensajes de control en un periodo de tiempo (por ejemplo, 60 s), la ESP32 se reinicia para restablecer la conexión.

## Código MicroPython corregido

```python
# main.py – Control secuencial de 5 bombas de diafragma vía MQTT
# ESP32 + MicroPython

from umqtt.simple import MQTTClient
from machine import Pin, reset
import network
import time
import ujson

# =========================
# 1. CONFIGURACIÓN WiFi
# =========================
SSID = "TuSSID"          # reemplaza con el nombre de tu red
PASSWORD = "TuPassword"  # reemplaza con la contraseña

# =========================
# 2. CONFIGURACIÓN MQTT
# =========================
MQTT_BROKER = "192.168.1.100"  # IP del broker MQTT (por ejemplo, la Raspberry Pi)
MQTT_TOPIC_CMD = b"linea/pintura/cmd"     # topic de entrada de comandos
MQTT_TOPIC_STATUS = b"linea/pintura/status"  # topic de salida para reportar estados
CLIENT_ID = b"ESP32_LINEA_PINTURA"         # identificador único del cliente

# =========================
# 3. CONFIGURACIÓN DE SALIDAS
# =========================
# definimos 5 pines para las bombas (conecta cada uno a un relé o transistor adecuado)
PUMP_PINS = [5, 18, 19, 21, 22]
pumps = [Pin(p, Pin.OUT) for p in PUMP_PINS]
for p in pumps:
    p.value(0)  # inicializa todas las bombas apagadas

# LED indicador (puede ser el integrado de la placa o uno externo)
LED_PIN = 2
led = Pin(LED_PIN, Pin.OUT)
led.value(0)

# =========================
# 4. ESTRUCTURA DE ESTADO DE LOS SENSORES
# =========================
# sensor_data es una lista de 5 diccionarios (uno por bomba) que almacena
# las señales lógicas de la galga y la temperatura
sensor_data = [
    {"galga": 0, "temp_ok": 0},  # bomba 1
    {"galga": 0, "temp_ok": 0},  # bomba 2
    {"galga": 0, "temp_ok": 0},  # bomba 3
    {"galga": 0, "temp_ok": 0},  # bomba 4
    {"galga": 0, "temp_ok": 0},  # bomba 5
]

# tiempo de funcionamiento de cada bomba (en segundos)
PUMP_RUNTIME_SEC = 2.0
# tiempo máximo sin recibir mensajes antes de reiniciar (seguridad)
MQTT_TIMEOUT_SEC = 60
# marca de tiempo del último mensaje recibido
last_msg_ts = time.time()


def conectar_wifi():
    """Conecta la ESP32 a la red Wi‑Fi."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Conectando a WiFi…")
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("Conectado a WiFi:", wlan.ifconfig())


def mqtt_callback(topic, msg):
    """
    Función que se ejecuta cuando llega un mensaje al topic suscrito.
    Se espera un JSON con claves pX_galga y pX_temp (donde X es 1…5).
    Actualiza la estructura sensor_data con 0 o 1.
    """
    global sensor_data, last_msg_ts
    last_msg_ts = time.time()
    print("Mensaje MQTT recibido:", msg)
    try:
        data = ujson.loads(msg)
        # actualiza las señales para cada bomba
        for i in range(5):
            g_key = "p{}_galga".format(i + 1)
            t_key = "p{}_temp".format(i + 1)
            if g_key in data:
                sensor_data[i]["galga"] = 1 if int(data[g_key]) == 1 else 0
            if t_key in data:
                sensor_data[i]["temp_ok"] = 1 if int(data[t_key]) == 1 else 0
    except Exception as e:
        print("Error parseando JSON:", e)


def conectar_mqtt():
    """Configura el cliente MQTT, asigna la callback, se conecta y se suscribe."""
    client = MQTTClient(CLIENT_ID, MQTT_BROKER)
    client.set_callback(mqtt_callback)
    client.connect()
    print("Conectado al broker MQTT")
    client.subscribe(MQTT_TOPIC_CMD)
    print("Suscrito al topic:", MQTT_TOPIC_CMD)
    return client


def activar_bomba(idx, client):
    """
    Enciende la bomba indicada por idx (0…4) durante un tiempo fijado,
    enciende el LED, y publica mensajes de inicio y fin.
    """
    print("Activando bomba", idx + 1)
    pumps[idx].value(1)
    led.value(1)
    try:
        client.publish(MQTT_TOPIC_STATUS, b"BOMBA_%d_ON" % (idx + 1))
    except:
        pass
    time.sleep(PUMP_RUNTIME_SEC)
    pumps[idx].value(0)
    led.value(0)
    print("Bomba", idx + 1, "apagada")
    try:
        client.publish(MQTT_TOPIC_STATUS, b"BOMBA_%d_OFF" % (idx + 1))
    except:
        pass


def loop_principal():
    """Bucle principal: recibe mensajes y activa bombas secuencialmente."""
    conectar_wifi()
    client = conectar_mqtt()
    while True:
        # comprueba si hay mensajes nuevos
        client.check_msg()
        # recorre las 5 bombas en orden
        for i in range(5):
            if sensor_data[i]["galga"] == 1 and sensor_data[i]["temp_ok"] == 1:
                activar_bomba(i, client)
                # pequeña pausa entre bombas para no saturar el micro
                time.sleep(0.3)
        # reinicia si no llega MQTT en el tiempo establecido
        if (time.time() - last_msg_ts) > MQTT_TIMEOUT_SEC:
            print("No llegan comandos MQTT desde hace tiempo, reiniciando…")
            for p in pumps:
                p.value(0)
            led.value(0)
            time.sleep(1)
            reset()
        # breve espera para reducir uso de CPU
        time.sleep(0.1)


try:
    loop_principal()
except Exception as e:
    print("Error en ejecución:", e)
    for p in pumps:
        p.value(0)
    led.value(0)
    time.sleep(5)
    reset()
```

## Descripción del flujo del código

1. **Importación de módulos**: se importan librerías necesarias para MQTT, manejo de pines, conexión Wi‑Fi y parseo de JSON.

2. **Configuración Wi‑Fi y MQTT**: se definen las credenciales de la red, la dirección del broker MQTT y los topics utilizados.

3. **Asignación de pines**: se definen los pines de la ESP32 que controlarán las bombas a través de relés/transistores y un LED de estado.

4. **Estructura de estado**: `sensor_data` almacena el estado de galga y temp_ok para cada bomba. Estas señales se actualizan cuando llega un mensaje MQTT.

5. **Conexión Wi‑Fi**: la función `conectar_wifi()` activa la interfaz STA y espera hasta tener una dirección IP.

6. **Callback MQTT**: cuando llega un mensaje al topic de comandos, se llama a `mqtt_callback()`. Esta función intenta interpretar el mensaje como JSON y actualiza `sensor_data` con los valores correspondientes.

7. **Conexión y suscripción MQTT**: la función `conectar_mqtt()` crea un cliente, asigna la callback y se suscribe al topic de comandos.

8. **Activación de bomba**: `activar_bomba()` se encarga de encender la bomba durante un periodo fijo, encender el LED, enviar un mensaje de estado y apagar la bomba después de dicho periodo.

9. **Bucle principal**: se conecta a Wi‑Fi y al broker, luego continuamente:
   - Revisa si hay nuevos mensajes (`client.check_msg()`).
   - Recorre cada bomba. Si galga y temp_ok son 1, llama a `activar_bomba()` para esa bomba.
   - Supervisa el tiempo transcurrido sin mensajes. Si supera el límite definido, reinicia la ESP32.
   - Introduce pequeños retardos para no saturar el CPU.

10. **Manejo de errores**: en caso de excepción, se apagan todas las bombas y el LED, se espera un poco y se reinicia el microcontrolador.

## Formato de los mensajes MQTT

### Topic de entrada `linea/pintura/cmd`

Se espera un JSON con las señales 0/1 para cada bomba. Ejemplo:

```json
{
  "p1_galga": 1,
  "p1_temp": 1,
  "p2_galga": 1,
  "p2_temp": 0,
  "p3_galga": 0,
  "p3_temp": 0,
  "p4_galga": 1,
  "p4_temp": 1,
  "p5_galga": 1,
  "p5_temp": 1
}
```

Para cada bomba `pX`, la clave `pX_galga` vale 1 si hay pintura y `pX_temp` vale 1 si la temperatura está dentro del rango.

La ESP32 actualiza su estructura `sensor_data` con estos valores.

### Topic de salida `linea/pintura/status`

La ESP32 publica mensajes de texto indicando el estado de cada bomba:

- `BOMBA_1_ON`
- `BOMBA_1_OFF`
- `BOMBA_2_ON`
- `BOMBA_2_OFF`
- …

Cada par de mensajes indica que la bomba correspondiente se encendió y luego se apagó tras su ciclo de funcionamiento.

## Integración con Node‑RED

A continuación se describe un flujo básico para verificar el funcionamiento utilizando Node‑RED.

### Nodos necesarios

- **mqtt in**: se conecta al mismo broker y se suscribe a `linea/pintura/status`. Permite monitorizar cuándo se encienden y apagan las bombas.

- **mqtt out**: se conecta al broker y publica en `linea/pintura/cmd`. Desde aquí se envían los JSON de control con los valores de galga y temp_ok para cada bomba.

- **debug o ui_led**: muestra los mensajes recibidos o enciende un indicador en un dashboard cuando se activa una bomba. Así se puede visualizar que la ESP32 está respondiendo correctamente.

### Flujo lógico

1. **Envía datos**: desde un nodo mqtt out en Node‑RED, se publica un JSON con los valores de galga y temp_ok para cada bomba. Esto simula la salida de los sensores o del sistema de control.

2. **Procesamiento en la ESP32**: la ESP32 recibe el JSON, actualiza sus señales y ejecuta el ciclo secuencial. Cuando activa una bomba, publica un mensaje `BOMBA_X_ON` y cuando la apaga publica `BOMBA_X_OFF`.

3. **Recepción en Node‑RED**: el nodo mqtt in recibe estos mensajes y los muestra en un debug o en un LED del dashboard para verificar visualmente que el ciclo de activación de bombas funciona.

## Conexión eléctrica (resumen)

- **Relé o transistor**: cada salida de la ESP32 no puede alimentar directamente una bomba de diafragma; es necesario usar un módulo relé o un transistor MOSFET que permita conmutar la alimentación de la bomba.

- **Fuente externa**: las bombas deben tener una fuente de alimentación adecuada y preferiblemente separada de la ESP32. El relé o MOSFET se utiliza para cerrar el circuito de la bomba.

- **LED de estado**: el LED integrado o un LED externo sirve para confirmar visualmente que alguna bomba está funcionando.

## Checklist de pruebas

1. Cargar `main.py` en la ESP32 usando ampy, Thonny u otra herramienta compatible con MicroPython.

2. Conectar la ESP32 a la red Wi‑Fi y verificar en el monitor serie que obtiene una IP y se suscribe al broker.

3. Desde Node‑RED o cualquier cliente MQTT, publicar en `linea/pintura/cmd` un JSON como:

```json
{
  "p1_galga": 1,
  "p1_temp": 1,
  "p2_galga": 0,
  "p2_temp": 0
}
```

4. Observar que la ESP32 enciende la bomba 1 durante el tiempo configurado y que el LED se ilumina.

5. Comprobar que se reciben `BOMBA_1_ON` y, después del tiempo, `BOMBA_1_OFF` en el topic de estado.

6. Realizar pruebas con las cinco bombas para asegurar que la secuencia y el reinicio funcionan correctamente.

## Notas finales

- La lógica que decide si la temperatura está dentro del rango se debe procesar fuera de la ESP32 y enviar sólo valores 0/1 para simplificar el código.

- El tiempo de funcionamiento (`PUMP_RUNTIME_SEC`) y el tiempo máximo sin mensajes (`MQTT_TIMEOUT_SEC`) pueden ajustarse según las necesidades del proceso.

- Si se requiere que una bomba no se vuelva a activar hasta recibir una nueva orden, puede añadirse una bandera adicional en `sensor_data` para indicar que ya fue procesada.


