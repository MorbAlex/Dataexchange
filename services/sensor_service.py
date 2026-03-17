from __future__ import annotations

from typing import Any

from db import connection, utc_now


def scale_value(raw_value: float, min_raw: float, max_raw: float, min_scaled: float, max_scaled: float) -> float:
    if max_raw == min_raw:
        return min_scaled
    ratio = (raw_value - min_raw) / (max_raw - min_raw)
    return min_scaled + ratio * (max_scaled - min_scaled)



def classify_value(value: float, alarm_low: float | None, alarm_high: float | None) -> str:
    if alarm_low is not None and value < alarm_low:
        return "low_alarm"
    if alarm_high is not None and value > alarm_high:
        return "high_alarm"
    return "ok"



def get_all_sensor_configs() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM sensor_config ORDER BY id").fetchall()
        return [dict(r) for r in rows]



def get_sensor_statuses() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT c.*, s.raw_value, s.scaled_value, s.state, s.updated_at
            FROM sensor_config c
            LEFT JOIN sensor_status s ON s.sensor_id = c.id
            ORDER BY c.id
            """
        ).fetchall()
        return [dict(r) for r in rows]



def get_sensor(sensor_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM sensor_config WHERE id = ?", (sensor_id,)).fetchone()
        return dict(row) if row else None



def update_sensor_config(sensor_id: int, data: dict[str, Any]) -> None:
    fields = [
        "name", "enabled", "channel", "unit", "min_raw", "max_raw",
        "min_scaled", "max_scaled", "alarm_low", "alarm_high", "sample_interval_ms"
    ]
    values = [data.get(field) for field in fields]
    values.append(sensor_id)
    with connection() as conn:
        conn.execute(
            f"UPDATE sensor_config SET {', '.join(f'{field} = ?' for field in fields)} WHERE id = ?",
            values,
        )



def record_sensor_reading(sensor_id: int, raw_value: float) -> None:
    sensor = get_sensor(sensor_id)
    if not sensor or not sensor["enabled"]:
        return
    scaled = scale_value(
        raw_value,
        float(sensor["min_raw"]),
        float(sensor["max_raw"]),
        float(sensor["min_scaled"]),
        float(sensor["max_scaled"]),
    )
    state = classify_value(scaled, sensor["alarm_low"], sensor["alarm_high"])
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO sensor_status (sensor_id, raw_value, scaled_value, state, updated_at, uploaded_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(sensor_id) DO UPDATE SET
                raw_value = excluded.raw_value,
                scaled_value = excluded.scaled_value,
                state = excluded.state,
                updated_at = excluded.updated_at,
                uploaded_at = NULL
            """,
            (sensor_id, raw_value, scaled, state, now),
        )
        conn.execute(
            """
            INSERT INTO sensor_history (sensor_id, raw_value, scaled_value, state, created_at, uploaded)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (sensor_id, raw_value, scaled, state, now),
        )



def get_recent_history(limit: int = 100) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT h.*, c.name, c.unit
            FROM sensor_history h
            JOIN sensor_config c ON c.id = h.sensor_id
            ORDER BY h.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]



def get_unsent_history(limit: int = 50) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT h.*, c.name, c.unit
            FROM sensor_history h
            JOIN sensor_config c ON c.id = h.sensor_id
            WHERE h.uploaded = 0
            ORDER BY h.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]



def mark_history_uploaded(ids: list[int]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    with connection() as conn:
        conn.execute(f"UPDATE sensor_history SET uploaded = 1 WHERE id IN ({placeholders})", ids)
        conn.execute(
            f"UPDATE sensor_status SET uploaded_at = ? WHERE sensor_id IN (SELECT DISTINCT sensor_id FROM sensor_history WHERE id IN ({placeholders}))",
            [utc_now(), *ids],
        )
