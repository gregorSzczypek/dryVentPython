import utime
import machine
import network
import ujson
import urequests
import gc
import dht
from machine import Pin

# Configuration
project_id = 'dryvent-dceb6'
settings_path = 'settings/thresholds'
sensor_path = 'sensor/current'
base_url = 'https://firestore.googleapis.com/v1/projects/{}/databases/(default)/documents'.format(project_id)
settings_url = '{}/{}'.format(base_url, settings_path)
sensor_url = '{}/{}'.format(base_url, sensor_path)
headers = {'Content-Type': 'application/json'}

# WiFi credentials
ssid = 'Datenautobahn'
password = 'Ausfahrt666'

# GPIO Setup
vent_pin = Pin(22, Pin.OUT)  # Adjust pin number as needed
vent_pin_n = Pin(21, Pin.OUT)
vent_pin.value(0)  # Ensure vent is initially off
vent_pin_n.value(0)

# DHT11 Sensor Setup
dht_pin = Pin(14)  # Adjust pin number as needed
dht_sensor = dht.DHT11(dht_pin)

# Define the pin for the LED
led_pin = machine.Pin("LED", machine.Pin.OUT)
led_time = 1

# Initial states
max_humidity = 0
min_humidity = 0
max_temperature = 0
min_temperature = 0
override_on = False
vent_on = False
is_manual_vent_on = False
timeout = 900000  # 15 min timeout for reaching min threshold
start_time = utime.ticks_ms()  # Start time for timeout

# Connect to Wi-Fi
wifi = network.WLAN(network.STA_IF)


def connectToWifi():
    while not wifi.isconnected():
        wifi.active(True)
        wifi.connect(ssid, password)
        utime.sleep(10)

    # print('Connected to Wi-Fi')
    # print('IP Address:', wifi.ifconfig()[0])


connectToWifi()

while led_time > 0.1:
    utime.sleep(led_time)
    led_pin.toggle()
    led_time = led_time - 0.1

led_pin.low()


def get_firestore_data(url):
    try:
        response = urequests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            # print("Failed to get data:", response.status_code)
            return None
    except Exception as e:
        # print("Failed to get data from Firestore")
        # print("Exception:", e)
        return None


def update_firestore(url, data):
    retries = 0
    while retries < 2:
        try:
            response = urequests.get(url, headers=headers, timeout=10)
            existing_data = response.json()

            for key, value in data.items():
                existing_data['fields'][key] = {'booleanValue' if isinstance(value, bool) else 'integerValue': value}

            response = urequests.patch(url, data=ujson.dumps(existing_data), headers=headers, timeout=10)
            if response.status_code == 200:
                # print("Data stored in Firestore successfully")
                response.close()
                return
            else:
                # print("Error storing data in Firestore. Status code:", response.status_code)
                response.close()
        except Exception as e:
            # print("Error storing data in Firestore:", str(e))
            response.close()

        retries += 1
        # print("Retrying... ({}/{})".format(retries, 2))
        utime.sleep(0.1)
    # print("Exceeded maximum retries. Failed to store data in Firestore.")
    connectToWifi()


def read_dht11():
    try:
        dht_sensor.measure()
        return dht_sensor.humidity(), dht_sensor.temperature()
    except Exception as e:
        # print("Failed to read from DHT11 sensor:", e)
        return None, None


def control_ventilator(humidity, temperature):
    global vent_on, override_on, max_humidity, max_temperature, min_humidity, min_temperature, start_time

    if override_on:
        vent_pin.value(1 if is_manual_vent_on else 0)
        vent_pin_n.value(1 if is_manual_vent_on else 0)
        vent_on = vent_pin.value() == 1
        update_firestore(sensor_url, {'ventilatorOn': vent_on})
        return

    current_time = utime.ticks_ms()

    if humidity > max_humidity or temperature > max_temperature:
        vent_on = True
        vent_pin.value(1)
        vent_pin_n.value(1)
        start_time = current_time  # Reset timeout timer
    elif (humidity <= min_humidity and temperature <= min_temperature) or (utime.ticks_diff(current_time, start_time) > timeout):
        vent_on = False
        vent_pin.value(0)
        vent_pin_n.value(0)

    update_firestore(sensor_url, {'ventilatorOn': vent_on})


while True:
    try:
        settings_data = get_firestore_data(settings_url)
        if settings_data:
            fields = settings_data.get("fields", {})
            max_humidity = int(fields.get("maxHumidity", {}).get("integerValue", max_humidity))
            min_humidity = int(fields.get("minHumidity", {}).get("integerValue", min_humidity))
            max_temperature = int(fields.get("maxTemperature", {}).get("integerValue", max_temperature))
            min_temperature = int(fields.get("minTemperature", {}).get("integerValue", min_temperature))
            override_on = bool(fields.get("overrideOn", {}).get("booleanValue", override_on))
            is_manual_vent_on = bool(fields.get("isManualVentOn", {}).get("booleanValue", is_manual_vent_on))

        sensor_data = get_firestore_data(sensor_url)
        if sensor_data:
            fields = sensor_data.get("fields", {})
            vent_on = fields.get("ventilatorOn", {}).get("booleanValue", False)

        current_humidity, current_temperature = read_dht11()
        if current_humidity is not None and current_temperature is not None:
            control_ventilator(current_humidity, current_temperature)

            update_firestore(sensor_url, {
                'humidity': current_humidity,
                'temperature': current_temperature
            })

        # print('Memory Allocation:', gc.mem_alloc(), 'bytes')
        # print('Memory Free:', gc.mem_free(), 'bytes')
        # print('IP Address:', wifi.ifconfig()[0])

        led_pin.toggle()
        utime.sleep(0.2)
        led_pin.toggle()
        utime.sleep(0.5)

    except Exception as e:
        # print("Exception occurred:", str(e))
        # print("Restarting Pico...")
        utime.sleep(1.0)
        machine.reset()
