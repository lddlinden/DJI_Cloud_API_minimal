#!/usr/bin/env python3
import os
import json
import sqlite3
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import paho
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

HOST_ADDR = os.environ.get("HOST_ADDR")
if not HOST_ADDR:
    raise ValueError("Environment variable HOST_ADDR is not set.")

MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")
DB_PATH = Path(os.environ.get("TELEMETRY_DB", "./data/telemetry.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

db = sqlite3.connect(DB_PATH, check_same_thread=False)

db.execute("""
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    topic TEXT NOT NULL,
    device_sn TEXT,
    device_type TEXT,
    latitude REAL,
    longitude REAL,
    height REAL,
    elevation REAL,
    vertical_speed REAL,
    horizontal_speed REAL,
    heading REAL,
    pitch REAL,
    roll REAL,
    battery REAL,
    battery_temperature REAL,
    battery_voltage REAL,
    remain_flight_time REAL,
    return_home_power REAL,
    landing_power REAL,
    satellites INTEGER,
    rtk_satellites INTEGER,
    home_distance REAL,
    wind_direction REAL,
    wind_speed REAL,
    gimbal_pitch REAL,
    gimbal_roll REAL,
    gimbal_yaw REAL,
    payload_index TEXT,
    camera_mode REAL,
    recording_state REAL,
    record_time REAL,
    zoom_factor REAL,
    ir_zoom_factor REAL,
    thermal_palette REAL,
    thermal_gain_mode REAL,
    thermal_global_temperature_max REAL,
    thermal_global_temperature_min REAL,
    thermal_isotherm_lower_limit REAL,
    thermal_isotherm_upper_limit REAL,
    thermal_isotherm_state REAL,
    raw_json TEXT NOT NULL
)
""")

# Allows this version to work with an existing telemetry.db created by
# an earlier version, without requiring a migration script.
existing_columns = {
    row[1] for row in db.execute("PRAGMA table_info(telemetry)").fetchall()
}

columns_to_add = {
    "battery_temperature": "REAL",
    "battery_voltage": "REAL",
    "remain_flight_time": "REAL",
    "return_home_power": "REAL",
    "landing_power": "REAL",
    "home_distance": "REAL",
    "wind_direction": "REAL",
    "wind_speed": "REAL",
    "gimbal_pitch": "REAL",
    "gimbal_roll": "REAL",
    "gimbal_yaw": "REAL",
    "payload_index": "TEXT",
    "camera_mode": "REAL",
    "recording_state": "REAL",
    "record_time": "REAL",
    "zoom_factor": "REAL",
    "ir_zoom_factor": "REAL",
    "thermal_palette": "REAL",
    "thermal_gain_mode": "REAL",
    "thermal_global_temperature_max": "REAL",
    "thermal_global_temperature_min": "REAL",
    "thermal_isotherm_lower_limit": "REAL",
    "thermal_isotherm_upper_limit": "REAL",
    "thermal_isotherm_state": "REAL",
}

for column, column_type in columns_to_add.items():
    if column not in existing_columns:
        print(f"Adding database column: {column}")
        db.execute(f"ALTER TABLE telemetry ADD COLUMN {column} {column_type}")

db.commit()


def number(data, key):
    try:
        value = data.get(key)
        return float(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def integer(data, key):
    value = number(data, key)
    return int(value) if value is not None else None


def find_payloads(data):
    """Find DJI payload objects such as 67-0-0 dynamically."""
    result = {}
    for key, value in data.items():
        if (
            isinstance(key, str)
            and key.count("-") == 2
            and all(part.isdigit() for part in key.split("-"))
            and isinstance(value, dict)
        ):
            result[key] = value
    return result


def handle_osd_message(topic, message):
    data = message.get("data")
    if not isinstance(data, dict):
        print(f"OSD message has no object in data: {topic}")
        return

    parts = topic.split("/")
    device_sn = (
        parts[2]
        if len(parts) >= 4 and parts[:2] == ["thing", "product"]
        else None
    )

    # OSD on the aircraft contains attitude/battery/position data.
    # Controller OSD has a much smaller/different structure.
    device_type = "aircraft" if "attitude_head" in data and "battery" in data else "controller"

    if device_type != "aircraft":
        return

    # DJI payload blocks are keyed as type-subtype-gimbalindex.
    # For the Mavic 3T the observed payload is 67-0-0.
    payloads = find_payloads(data)

    payload_index = None
    payload = {}

    for key, value in payloads.items():
        if value.get("payload_index"):
            payload_index = str(value["payload_index"])
            payload = value
            break

    if not payload and payloads:
        payload_index, payload = next(iter(payloads.items()))

    cameras = data.get("cameras")
    camera = cameras[0] if isinstance(cameras, list) and cameras and isinstance(cameras[0], dict) else {}

    battery = data.get("battery")
    if not isinstance(battery, dict):
        battery = {}

    batteries = battery.get("batteries")
    battery0 = (
        batteries[0]
        if isinstance(batteries, list) and batteries and isinstance(batteries[0], dict)
        else {}
    )

    # Prefer the top-level battery capacity, which matches the observed DJI OSD.
    battery_percent = number(battery, "capacity_percent")
    if battery_percent is None:
        battery_percent = number(battery0, "capacity_percent")

    # Gimbal values are in data["67-0-0"] for the observed Mavic 3T OSD.
    gimbal_pitch = number(payload, "gimbal_pitch")
    gimbal_roll = number(payload, "gimbal_roll")
    gimbal_yaw = number(payload, "gimbal_yaw")

    # Camera values are also present in cameras[0].
    # Payload block zoom is retained as the primary zoom value because it
    # belongs to the same payload block as the gimbal.
    zoom_factor = number(payload, "zoom_factor")
    if zoom_factor is None:
        zoom_factor = number(camera, "zoom_factor")

    ir_zoom_factor = number(camera, "ir_zoom_factor")
    if ir_zoom_factor is None:
        ir_zoom_factor = number(payload, "ir_zoom_factor")

    position = data.get("position_state")
    if not isinstance(position, dict):
        position = {}

    row = (
        datetime.now(timezone.utc).isoformat(),
        topic,
        device_sn,
        device_type,
        number(data, "latitude"),
        number(data, "longitude"),
        number(data, "height"),
        number(data, "elevation"),
        number(data, "vertical_speed"),
        number(data, "horizontal_speed"),
        number(data, "attitude_head"),
        number(data, "attitude_pitch"),
        number(data, "attitude_roll"),
        battery_percent,
        number(battery0, "temperature"),
        number(battery0, "voltage"),
        number(battery, "remain_flight_time"),
        number(battery, "return_home_power"),
        number(battery, "landing_power"),
        integer(position, "gps_number"),
        integer(position, "rtk_number"),
        number(data, "home_distance"),
        number(data, "wind_direction"),
        number(data, "wind_speed"),
        gimbal_pitch,
        gimbal_roll,
        gimbal_yaw,
        payload_index,
        number(camera, "camera_mode"),
        number(camera, "recording_state"),
        number(camera, "record_time"),
        zoom_factor,
        ir_zoom_factor,
        number(payload, "thermal_current_palette_style"),
        number(payload, "thermal_gain_mode"),
        number(payload, "thermal_global_temperature_max"),
        number(payload, "thermal_global_temperature_min"),
        number(payload, "thermal_isotherm_lower_limit"),
        number(payload, "thermal_isotherm_upper_limit"),
        number(payload, "thermal_isotherm_state"),
        json.dumps(message, ensure_ascii=False),
    )

    db.execute("""
        INSERT INTO telemetry (
            received_at, topic, device_sn, device_type,
            latitude, longitude, height, elevation,
            vertical_speed, horizontal_speed,
            heading, pitch, roll,
            battery, battery_temperature, battery_voltage,
            remain_flight_time, return_home_power, landing_power,
            satellites, rtk_satellites,
            home_distance, wind_direction, wind_speed,
            gimbal_pitch, gimbal_roll, gimbal_yaw,
            payload_index, camera_mode, recording_state, record_time,
            zoom_factor, ir_zoom_factor,
            thermal_palette, thermal_gain_mode,
            thermal_global_temperature_max,
            thermal_global_temperature_min,
            thermal_isotherm_lower_limit,
            thermal_isotherm_upper_limit,
            thermal_isotherm_state,
            raw_json
        )
        VALUES (
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?,
            ?
        )
    """, row)
    db.commit()

    print(
        f"OSD aircraft {device_sn or '-'} | "
        f"battery={battery_percent} height={number(data, 'height')} "
        f"heading={number(data, 'attitude_head')} "
        f"pitch={number(data, 'attitude_pitch')} roll={number(data, 'attitude_roll')} | "
        f"payload={payload_index} "
        f"gimbal=({gimbal_pitch},{gimbal_roll},{gimbal_yaw}) "
        f"zoom={zoom_factor} ir_zoom={ir_zoom_factor}"
    )


def on_connect(client, userdata, flags, rc, properties=None):
    print("Connected with result code " + str(rc))
    client.subscribe("sys/#")
    client.subscribe("thing/#")


def on_message(client, userdata, msg):
    try:
        message = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"Invalid JSON on {msg.topic}: {e}")
        return

    print("Got msg:", msg.topic)

    if msg.topic.endswith("status"):
        if message.get("method") != "update_topo":
            return

        response = {
            "tid": message["tid"],
            "bid": message["bid"],
            "timestamp": message["timestamp"] + 2,
            "data": {"result": 0},
        }
        client.publish(msg.topic + "_reply", payload=json.dumps(response))
        print("published status reply")

    elif msg.topic.endswith("osd") and msg.topic.startswith("thing/product/"):
        handle_osd_message(msg.topic, message)


PAHO_MAIN_VER = int(version("paho-mqtt").split(".")[0])

if PAHO_MAIN_VER == 1:
    client = mqtt.Client(transport="tcp")
elif PAHO_MAIN_VER == 2:
    client = mqtt.Client(
        paho.mqtt.enums.CallbackAPIVersion.VERSION2,
        transport="tcp",
    )
else:
    raise RuntimeError(f"Unsupported paho-mqtt major version: {PAHO_MAIN_VER}")

client.on_connect = on_connect
client.on_message = on_message

if MQTT_USERNAME:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

client.connect(HOST_ADDR, MQTT_PORT, 60)

print(f"Telemetry database: {DB_PATH.resolve()}")
client.loop_forever()
