"""me193_gait: forward IMU samples from the sketch to MQTT.

The sketch reads the MPU-6050 at 50 Hz and calls Bridge.notify("imu_sample",
t, ax, ay, az, gx, gy, gz) for every sample. This side batches them and
publishes to RAW_TOPIC in the format laptop/logger.py and laptop/simulator.py
use:
    ~10 messages/s, each a JSON list of 5 samples:
    [{"t": 1240, "ax": 0.98, "ay": 0.01, "az": 0.12,
      "gx": -0.4, "gy": 12.7, "gz": 0.9}, ...]
    t is integer ms since the sketch started; accel in g, gyro in deg/s.

MQTT never slows the sensor: the sketch's notify is fire-and-forget, the Bridge
handler only appends to a batch, and a separate thread publishes from a bounded
queue. While MQTT is down (e.g. WiFi drop) up to QUEUE_SECONDS of batches are
kept and sent on reconnect; older ones are dropped, which shows up as a gap in
t. paho reconnects by itself (connect_async + loop_start).

Every STATUS_PERIOD_S this also publishes STATUS_TOPIC:
    {"wall": <board Unix time>, "t": <last sample t>, "rate_hz": ...,
     "queued": <batches waiting>, "dropped": ..., "mqtt": true/false,
     "mcu": <last sketch status line>}
"wall" and "t" let the laptop estimate end-to-end lag.
"""
import collections
import json
import threading
import time

import paho.mqtt.client as mqtt

from arduino.app_utils import App, Bridge, Logger

logger = Logger("me193_gait")

BROKER = ("broker.hivemq.com", 1883)
RAW_TOPIC = "ME193/ceci/gait/raw"
STATUS_TOPIC = "ME193/ceci/gait/status"

FS = 50
BATCH = 5                   # samples per message -> 10 messages/s
QUEUE_SECONDS = 30          # buffer this much while MQTT is down
STATUS_PERIOD_S = 5.0

batch = []
queue = collections.deque(maxlen=QUEUE_SECONDS * FS // BATCH)
queue_ready = threading.Event()
lock = threading.Lock()

received = 0                # samples from the sketch since the last status
dropped = 0                 # batches dropped because the queue was full
last_t = None
last_mcu_status = ""
mqtt_up = False


def on_connect(client, userdata, flags, reason_code, properties):
    global mqtt_up
    mqtt_up = not reason_code.is_failure
    logger.info(f"MQTT connected to {BROKER[0]} ({reason_code})")
    queue_ready.set()   # flush anything queued while we were down


def on_disconnect(client, userdata, flags, reason_code, properties):
    global mqtt_up
    if mqtt_up:
        logger.warning(f"MQTT disconnected ({reason_code}); reconnecting")
    mqtt_up = False


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.reconnect_delay_set(1, 10)
client.connect_async(*BROKER, keepalive=30)
client.loop_start()


def imu_sample(t, ax, ay, az, gx, gy, gz):
    """Bridge handler, once per sample. Must stay fast: no I/O here."""
    global received, dropped, last_t
    sample = {"t": int(t),
              "ax": round(ax, 4), "ay": round(ay, 4), "az": round(az, 4),
              "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2)}
    with lock:
        received += 1
        last_t = sample["t"]
        batch.append(sample)
        if len(batch) == BATCH:
            if len(queue) == queue.maxlen:
                dropped += 1    # deque drops the oldest batch
            queue.append(json.dumps(batch))
            batch.clear()
            queue_ready.set()


def imu_status(text):
    global last_mcu_status
    last_mcu_status = text
    logger.info(f"sketch: {text}")


def publisher():
    """Publish queued batches in order while MQTT is up."""
    while True:
        queue_ready.wait()
        queue_ready.clear()
        while mqtt_up:
            with lock:
                if not queue:
                    break
                payload = queue[0]
            info = client.publish(RAW_TOPIC, payload, qos=0)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                break           # not connected after all; retry on reconnect
            with lock:
                if queue and queue[0] is payload:
                    queue.popleft()


def status_loop():
    """App loop: log and publish a status line every STATUS_PERIOD_S."""
    global received, dropped
    time.sleep(STATUS_PERIOD_S)
    with lock:
        rate = received / STATUS_PERIOD_S
        n_queued, n_dropped = len(queue), dropped
        received = 0
        dropped = 0
    status = {"wall": round(time.time(), 3), "t": last_t, "rate_hz": rate,
              "queued": n_queued, "dropped": n_dropped, "mqtt": mqtt_up,
              "mcu": last_mcu_status}
    logger.info(f"rate {rate:.1f} Hz, queued {n_queued}, dropped {n_dropped}, "
                f"MQTT {'up' if mqtt_up else 'DOWN'}")
    if mqtt_up:
        client.publish(STATUS_TOPIC, json.dumps(status), qos=0)


Bridge.provide("imu_sample", imu_sample)
Bridge.provide("imu_status", imu_status)
threading.Thread(target=publisher, daemon=True).start()

App.run(user_loop=status_loop)
