#!/usr/bin/env python3
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

load_dotenv()

DB_PATH = Path(os.environ.get("TELEMETRY_DB", "./data/telemetry.db"))
HTML_DIR = Path(__file__).parent / "cloudhtml"

app = FastAPI(title="DJI Bridge Telemetry")


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


@app.get("/", response_class=HTMLResponse)
def root():
    return telemetry()


@app.get("/telemetry", response_class=HTMLResponse)
def telemetry():
    return HTMLResponse(
        (HTML_DIR / "telemetry.html").read_text(encoding="utf-8")
    )


@app.get("/api/telemetry/latest")
def latest(limit: int = Query(100, ge=1, le=1000)):
    if not DB_PATH.exists():
        return JSONResponse(
            {
                "error": "Telemetry database does not exist",
                "db_path": str(DB_PATH.resolve()),
            },
            status_code=404,
        )

    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                id, received_at, topic, device_sn, device_type,
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
            FROM telemetry
            WHERE device_type = 'aircraft'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return JSONResponse([dict(row) for row in rows])


@app.get("/api/telemetry/all")
def all_devices(limit: int = Query(100, ge=1, le=1000)):
    if not DB_PATH.exists():
        return JSONResponse(
            {"error": "Telemetry database does not exist"},
            status_code=404,
        )

    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                id, received_at, topic, device_sn, device_type,
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
            FROM telemetry
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return JSONResponse([dict(row) for row in rows])


@app.get("/api/telemetry/debug")
def debug():
    if not DB_PATH.exists():
        return {
            "db_path": str(DB_PATH.resolve()),
            "db_exists": False,
            "total": 0,
            "aircraft": 0,
            "latest": None,
        }

    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
        aircraft = db.execute(
            "SELECT COUNT(*) FROM telemetry WHERE device_type='aircraft'"
        ).fetchone()[0]

        latest_row = db.execute(
            """
            SELECT id, received_at, device_sn, device_type, topic
            FROM telemetry
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

        columns = [
            row["name"]
            for row in db.execute("PRAGMA table_info(telemetry)").fetchall()
        ]

    return {
        "db_path": str(DB_PATH.resolve()),
        "db_exists": True,
        "total": total,
        "aircraft": aircraft,
        "columns": columns,
        "latest": dict(latest_row) if latest_row else None,
    }


if __name__ == "__main__":
    print(f"Telemetry DB: {DB_PATH.resolve()}")
    print("Telemetry page: http://0.0.0.0:3000/telemetry")
    uvicorn.run(app, host="0.0.0.0", port=3000)
