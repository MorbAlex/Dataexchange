import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify, render_template, abort

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "server_data.db"
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")
DEVICE_TIMEOUT_SECONDS = int(os.getenv("DEVICE_TIMEOUT_SECONDS", "15"))

app = Flask(__name__)


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            last_seen_at TEXT,
            last_upload_at TEXT,
            last_status TEXT,
            updated_at TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS latest_sensor_values (
            device_id TEXT NOT NULL,
            sensor_id INTEGER NOT NULL,
            sensor_name TEXT,
            raw_value REAL,
            scaled_value REAL,
            unit TEXT,
            state TEXT,
            created_at TEXT,
            received_at TEXT NOT NULL,
            PRIMARY KEY (device_id, sensor_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_record_id INTEGER,
            device_id TEXT NOT NULL,
            sensor_id INTEGER NOT NULL,
            sensor_name TEXT,
            raw_value REAL,
            scaled_value REAL,
            unit TEXT,
            state TEXT,
            created_at TEXT,
            received_at TEXT NOT NULL
        )
        """)

        conn.commit()


def auth_ok(req) -> bool:
    if not INGEST_TOKEN:
        return True

    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False

    token = header.split(" ", 1)[1].strip()
    return token == INGEST_TOKEN


@app.route("/ingest", methods=["POST"])
def ingest():
    if not auth_ok(request):
        abort(401)

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    device_id = str(payload.get("device") or "").strip()
    records = payload.get("records") or []

    if not device_id:
        return jsonify({"ok": False, "error": "missing device"}), 400

    if not isinstance(records, list):
        return jsonify({"ok": False, "error": "records must be a list"}), 400

    received_at = now_iso()

    with get_db() as conn:
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO devices (device_id, last_seen_at, last_upload_at, last_status, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            last_upload_at = excluded.last_upload_at,
            last_status = excluded.last_status,
            updated_at = excluded.updated_at
        """, (device_id, received_at, received_at, "connected", received_at))

        inserted = 0

        for r in records:
            sensor_id = int(r.get("sensor_id", 0))
            sensor_name = str(r.get("sensor_name", f"Sensor {sensor_id}"))
            raw_value = r.get("raw_value")
            scaled_value = r.get("scaled_value")
            unit = str(r.get("unit") or "")
            state = str(r.get("state") or "")
            created_at = str(r.get("created_at") or "")
            source_record_id = r.get("id")

            cur.execute("""
            INSERT INTO sensor_history (
                source_record_id, device_id, sensor_id, sensor_name,
                raw_value, scaled_value, unit, state, created_at, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_record_id, device_id, sensor_id, sensor_name,
                raw_value, scaled_value, unit, state, created_at, received_at
            ))

            cur.execute("""
            INSERT INTO latest_sensor_values (
                device_id, sensor_id, sensor_name,
                raw_value, scaled_value, unit, state, created_at, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, sensor_id) DO UPDATE SET
                sensor_name = excluded.sensor_name,
                raw_value = excluded.raw_value,
                scaled_value = excluded.scaled_value,
                unit = excluded.unit,
                state = excluded.state,
                created_at = excluded.created_at,
                received_at = excluded.received_at
            """, (
                device_id, sensor_id, sensor_name,
                raw_value, scaled_value, unit, state, created_at, received_at
            ))

            inserted += 1

        conn.commit()

    return jsonify({"ok": True, "device": device_id, "inserted": inserted})


def get_device_status(device_row):
    if not device_row or not device_row["last_seen_at"]:
        return "disconnected"

    last_seen = parse_iso(device_row["last_seen_at"])
    if not last_seen:
        return "disconnected"

    if now_utc() - last_seen <= timedelta(seconds=DEVICE_TIMEOUT_SECONDS):
        return "connected"

    return "disconnected"


@app.route("/")
def index():
    with get_db() as conn:
        device = conn.execute("""
            SELECT *
            FROM devices
            WHERE device_id = ?
        """, ("cm5-prototype",)).fetchone()

        sensors = conn.execute("""
            SELECT *
            FROM latest_sensor_values
            WHERE device_id = ?
            ORDER BY sensor_id
        """, ("cm5-prototype",)).fetchall()

    connection_state = get_device_status(device)

    return render_template(
        "index.html",
        device=device,
        sensors=sensors,
        connection_state=connection_state,
        device_timeout_seconds=DEVICE_TIMEOUT_SECONDS,
    )


@app.route("/api/device/<device_id>/live")
def api_device_live(device_id):
    with get_db() as conn:
        device = conn.execute("""
            SELECT *
            FROM devices
            WHERE device_id = ?
        """, (device_id,)).fetchone()

        sensors = conn.execute("""
            SELECT *
            FROM latest_sensor_values
            WHERE device_id = ?
            ORDER BY sensor_id
        """, (device_id,)).fetchall()

    return jsonify({
        "device_id": device_id,
        "connection_state": get_device_status(device),
        "last_seen_at": device["last_seen_at"] if device else None,
        "sensors": [
            {
                "sensor_id": s["sensor_id"],
                "sensor_name": s["sensor_name"],
                "raw_value": s["raw_value"],
                "scaled_value": s["scaled_value"],
                "unit": s["unit"],
                "state": s["state"],
                "created_at": s["created_at"],
                "received_at": s["received_at"],
            }
            for s in sensors
        ]
    })


@app.route("/api/device/<device_id>/history")
def api_device_history(device_id):
    limit = int(request.args.get("limit", "100"))

    with get_db() as conn:
        rows = conn.execute("""
            SELECT device_id, sensor_id, sensor_name, scaled_value, unit, state, created_at, received_at
            FROM sensor_history
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (device_id, limit)).fetchall()

    rows = list(reversed(rows))

    history = {
        "1": {"label": "Sensor 1", "unit": "", "points": []},
        "2": {"label": "Sensor 2", "unit": "", "points": []},
        "3": {"label": "Sensor 3", "unit": "", "points": []},
        "4": {"label": "Sensor 4", "unit": "", "points": []},
    }

    for r in rows:
        sid = str(r["sensor_id"])
        if sid not in history:
            history[sid] = {"label": r["sensor_name"], "unit": r["unit"], "points": []}

        history[sid]["label"] = r["sensor_name"] or history[sid]["label"]
        history[sid]["unit"] = r["unit"] or history[sid]["unit"]
        history[sid]["points"].append({
            "x": r["created_at"] or r["received_at"],
            "y": r["scaled_value"],
            "state": r["state"],
        })

    return jsonify({
        "device_id": device_id,
        "series": history
    })


if __name__ == "__main__":
    init_db()
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    app.run(host=host, port=port, debug=True)