from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_config (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    channel INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT 'V',
    min_raw REAL NOT NULL DEFAULT 0,
    max_raw REAL NOT NULL DEFAULT 1023,
    min_scaled REAL NOT NULL DEFAULT 0,
    max_scaled REAL NOT NULL DEFAULT 10,
    alarm_low REAL,
    alarm_high REAL,
    sample_interval_ms INTEGER NOT NULL DEFAULT 1000
);

CREATE TABLE IF NOT EXISTS sensor_status (
    sensor_id INTEGER PRIMARY KEY,
    raw_value REAL NOT NULL,
    scaled_value REAL NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    uploaded_at TEXT,
    FOREIGN KEY(sensor_id) REFERENCES sensor_config(id)
);

CREATE TABLE IF NOT EXISTS sensor_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    raw_value REAL NOT NULL,
    scaled_value REAL NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    uploaded INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(sensor_id) REFERENCES sensor_config(id)
);

CREATE TABLE IF NOT EXISTS modem_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    apn TEXT NOT NULL DEFAULT 'internet',
    pin TEXT DEFAULT '',
    preferred_mode TEXT NOT NULL DEFAULT 'auto',
    auto_connect INTEGER NOT NULL DEFAULT 0,
    roaming_allowed INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
        count = conn.execute("SELECT COUNT(*) AS c FROM sensor_config").fetchone()["c"]
        if count == 0:
            for idx in range(1, 5):
                conn.execute(
                    """
                    INSERT INTO sensor_config (
                        id, name, enabled, channel, unit,
                        min_raw, max_raw, min_scaled, max_scaled,
                        alarm_low, alarm_high, sample_interval_ms
                    ) VALUES (?, ?, 1, ?, 'V', 0, 1023, 0, 10, 1, 9, 1000)
                    """,
                    (idx, f"Sensor {idx}", idx - 1),
                )
        conn.execute(
            """
            INSERT INTO modem_config (id, apn, pin, preferred_mode, auto_connect, roaming_allowed)
            VALUES (1, 'internet', '', 'auto', 0, 0)
            ON CONFLICT(id) DO NOTHING
            """
        )


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
