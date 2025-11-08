# main.py - Control secuencial de 5 bombas de diafragma vía MQTT
# ESP32 + MicroPython

from umqtt.simple import MQTTClient
from machine import Pin, reset
import network
import time
import ujson

# =========================
# 1. CONFIGURACIÓN WiFi
# =========================
SSID = "TuSSID"          # <-- cámbialo
PASSWORD = "TuPassword"  # <-- cámbialo

# =========================
# 2. CONFIGURACIÓN MQTT
# =========================
MQTT_BROKER = "192.168.1.100"  # IP del broker (ej. Raspberry con Mosquitto)
MQTT_TOPIC_CMD = b"linea/pintura/cmd"      # por aquí LLEGAN los 0/1 de galga y temperatura
MQTT_TOPIC_STATUS = b"linea/pintura/status"  # por aquí REPORTA la ESP32
CLIENT_ID = b"ESP32_LINEA_PINTURA"

# =========================
# 3. CONFIGURACIÓN DE SALIDAS
# =========================
# 5 bombas en 5 pines distintos (usa relés o driver adecuado)
PUMP_PINS = [5, 18, 19, 21, 22]
pumps = [Pin(p, Pin.OUT) for p in PUMP_PINS]
for p in pumps:
    p.value(0)  # todas apagadas al inicio

# LED indicador de bomba activa
LED_PIN = 2  # en muchas ESP32 es el LED integrado
led = Pin(LED_PIN, Pin.OUT)
led.value(0)

# =========================
# 4. ESTADO DE SENSORES (lo que llega por MQTT)
# Cada bomba tiene 2 banderas:
#   - galga: 1 hay pintura / 0 no hay
#   - temp_ok: 1 temperatura dentro de 22-28 / 0 fuera de rango
# =========================
sensor_data = [
    {"galga": 0, "temp_ok": 0},  # bomba 1
    {"galga": 0, "temp_ok": 0},  # bomba 2
    {"galga": 0, "temp_ok": 0},  # bomba 3
    {"galga": 0, "temp_ok": 0},  # bomba 4
    {"galga": 0, "temp_ok": 0},  # bomba 5
]

# cuánto tiempo mantiene encendida cada bomba (ajusta a tu proceso)
PUMP_RUNTIME_SEC = 2.0

# si no llega nada por MQTT en este tiempo, se reinicia
MQTT_TIMEOUT_SEC = 60
last_msg_ts = time.time()


def conectar_wifi():
    """Conecta la ESP32 al WiFi indicado arriba."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Conectando a WiFi...")
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("Conectado a WiFi:", wlan.ifconfig())


def mqtt_callback(topic, msg):
    """
    Procesa lo que llega por MQTT en linea/pintura/cmd.
    Esperamos un JSON con pares pX_galga y pX_temp que valen 0 o 1.
    Ejemplo:
    {
      "p1_galga":1, "p1_temp":1,
      "p2_galga":1, "p2_temp":0,
      "p3_galga":0, "p3_temp":0,
      "p4_galga":1, "p4_temp":1,
      "p5_galga":1, "p5_temp":1
    }
    """
    global sensor_data, last_msg_ts
    last_msg_ts = time.time()
    print("Mensaje MQTT recibido:", msg)
    try:
        data = ujson.loads(msg)
        # actualizamos cada una de las 5 bombas
        for i in range(5):
            g_key = "p{}_galga".format(i + 1)
            t_key = "p{}_temp".format(i + 1)
            if g_key in data:
                sensor_data[i]["galga"] = 1 if int(data[g_key]) == 1 else 0
            if t_key in data:
                sensor_data[i]["temp_ok"] = 1 if int(data[t_key]) == 1 else 0
    except Exception as e:
        # si no es JSON válido, se ignora pero no rompemos el loop
        print("Error parseando JSON:", e)


def conectar_mqtt():
    """Crea cliente MQTT, setea callback, se conecta y se suscribe."""
    client = MQTTClient(CLIENT_ID, MQTT_BROKER)
    client.set_callback(mqtt_callback)
    client.connect()
    print("Conectado al broker MQTT")
    client.subscribe(MQTT_TOPIC_CMD)
    print("Suscrito a:", MQTT_TOPIC_CMD)
    return client


def activar_bomba(idx, client):
    """
    Enciende UNA bomba de la lista (idx 0..4) sólo el tiempo definido,
    enciende LED, y reporta por MQTT_TOPIC_STATUS.
    """
    print("Activando bomba", idx + 1)
    pumps[idx].value(1)
    led.value(1)
    # avisamos que se encendió
    try:
        client.publish(MQTT_TOPIC_STATUS, b"BOMBA_%d_ON" % (idx + 1))
    except:
        pass

    time.sleep(PUMP_RUNTIME_SEC)

    pumps[idx].value(0)
    led.value(0)
    print("Bomba", idx + 1, "apagada")

    # avisamos que se apagó
    try:
        client.publish(MQTT_TOPIC_STATUS, b"BOMBA_%d_OFF" % (idx + 1))
    except:
        pass


def loop_principal():
    """Loop principal: recibe MQTT y activa las bombas una por una."""
    conectar_wifi()
    client = conectar_mqtt()

    while True:
        # revisar si hay mensajes nuevos
        client.check_msg()

        # recorrer las 5 bombas secuencialmente
        for i in range(5):
            # si HAY pintura y temp está OK -> activar
            if sensor_data[i]["galga"] == 1 and sensor_data[i]["temp_ok"] == 1:
                activar_bomba(i, client)
                # pequeña pausa entre bombas para no saturar la ESP32
                time.sleep(0.3)

        # watchdog simple para MQTT
        if (time.time() - last_msg_ts) > MQTT_TIMEOUT_SEC:
            print("No llega MQTT hace mucho, reseteando...")
            for p in pumps:
                p.value(0)
            led.value(0)
            time.sleep(1)
            reset()

        # pequeño delay para que no se dispare el CPU
        time.sleep(0.1)


try:
    loop_principal()
except Exception as e:
    print("Error en ejecución:", e)
    # seguridad: apagar todo
    for p in pumps:
        p.value(0)
    led.value(0)
    time.sleep(5)
    reset()
