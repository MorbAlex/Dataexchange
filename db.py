import os
import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "gateway.db")))

SCHEMA = [
    '''
    CREATE TABLE IF NOT EXISTS sensor_config (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        channel INTEGER NOT NULL,
        unit TEXT NOT NULL DEFAULT 'V',
        min_raw REAL NOT NULL DEFAULT 0,
        max_raw REAL NOT NULL DEFAULT 4095,
        min_scaled REAL NOT NULL DEFAULT 0,
        max_scaled REAL NOT NULL DEFAULT 10,
        alarm_low REAL,
        alarm_high REAL,
        sample_interval_ms INTEGER NOT NULL DEFAULT 1000,
        updated_at TEXT NOT NULL
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS sensor_status (
        sensor_id INTEGER PRIMARY KEY,
        raw_value REAL,
        scaled_value REAL,
        state TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(sensor_id) REFERENCES sensor_config(id)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS sensor_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sensor_id INTEGER NOT NULL,
        raw_value REAL,
        scaled_value REAL,
        state TEXT,
        created_at TEXT NOT NULL,
        uploaded INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(sensor_id) REFERENCES sensor_config(id)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS modem_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        apn TEXT NOT NULL DEFAULT 'internet',
        pin TEXT DEFAULT '',
        auto_connect INTEGER NOT NULL DEFAULT 0,
        preferred_mode TEXT NOT NULL DEFAULT 'auto',
        roaming_allowed INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS modem_runtime (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        packet_data_handle TEXT DEFAULT '',
        last_ip TEXT DEFAULT '',
        last_status TEXT DEFAULT '',
        last_error TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS upload_runtime (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_upload_at TEXT DEFAULT '',
        last_upload_status TEXT DEFAULT '',
        last_upload_error TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    )
    '''
]

DEFAULT_SENSORS = [
    (1, 'Sensor 1', 1, 0, 'V', 0, 4095, 0, 10, 1, 9, 1000),
    (2, 'Sensor 2', 1, 1, 'V', 0, 4095, 0, 10, 1, 9, 1000),
    (3, 'Sensor 3', 1, 2, 'V', 0, 4095, 0, 10, 1, 9, 1000),
    (4, 'Sensor 4', 1, 3, 'V', 0, 4095, 0, 10, 1, 9, 1000),
]

def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def get_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)

        for row in DEFAULT_SENSORS:
            cur.execute(
                '''
                INSERT OR IGNORE INTO sensor_config
                (id, name, enabled, channel, unit, min_raw, max_raw, min_scaled, max_scaled, alarm_low, alarm_high, sample_interval_ms, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (*row, now_iso())
            )
            cur.execute(
                '''
                INSERT OR IGNORE INTO sensor_status
                (sensor_id, raw_value, scaled_value, state, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (row[0], 0.0, 0.0, 'offline', now_iso())
            )

        cur.execute(
            '''
            INSERT OR IGNORE INTO modem_config
            (id, apn, pin, auto_connect, preferred_mode, roaming_allowed, updated_at)
            VALUES (1, 'internet', '', 0, 'auto', 0, ?)
            ''',
            (now_iso(),)
        )
        cur.execute(
            '''
            INSERT OR IGNORE INTO modem_runtime
            (id, packet_data_handle, last_ip, last_status, last_error, updated_at)
            VALUES (1, '', '', 'disconnected', '', ?)
            ''',
            (now_iso(),)
        )
        cur.execute(
            '''
            INSERT OR IGNORE INTO upload_runtime
            (id, last_upload_at, last_upload_status, last_upload_error, updated_at)
            VALUES (1, '', '', '', ?)
            ''',
            (now_iso(),)
        )
        conn.commit()

def fetch_all(query, params=()):
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()

def fetch_one(query, params=()):
    with get_connection() as conn:
        return conn.execute(query, params).fetchone()

def execute(query, params=()):
    with get_connection() as conn:
        conn.execute(query, params)
        conn.commit()
