import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import traceback

import spidev


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "app.db"


class MCP3204Reader:
    def __init__(self, bus: int = 0, device: int = 0, max_speed_hz: int = 1_000_000):
        self.bus = bus
        self.device = device
        self.max_speed_hz = max_speed_hz
        self.spi = None
        self.open()

    def open(self) -> None:
        if self.spi is not None:
            try:
                self.spi.close()
            except Exception:
                pass

        self.spi = spidev.SpiDev()
        self.spi.open(self.bus, self.device)
        self.spi.max_speed_hz = self.max_speed_hz
        self.spi.mode = 0

    def read_channel(self, channel: int) -> int:
        if channel < 0 or channel > 3:
            raise ValueError(f"MCP3204 channel must be 0..3, got {channel}")

        # MCP3204 single-ended read
        tx = [0x06, (channel & 0x03) << 6, 0x00]
        rx = self.spi.xfer2(tx)
        value = ((rx[1] & 0x0F) << 8) | rx[2]
        return value

    def reconnect(self) -> None:
        self.open()

    def close(self) -> None:
        if self.spi is not None:
            self.spi.close()
            self.spi = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_sensor_configs(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, channel, unit,
               min_raw, max_raw,
               min_scaled, max_scaled,
               alarm_low, alarm_high,
               enabled, sample_interval_ms
        FROM sensor_config
        ORDER BY id
    """)
    return cur.fetchall()


def scale_value(
    raw_value: float,
    min_raw: float,
    max_raw: float,
    min_scaled: float,
    max_scaled: float,
) -> float:
    if max_raw == min_raw:
        return min_scaled

    if raw_value < min_raw:
        raw_value = min_raw
    elif raw_value > max_raw:
        raw_value = max_raw

    return min_scaled + ((raw_value - min_raw) / (max_raw - min_raw)) * (max_scaled - min_scaled)


def calc_state(value: float, alarm_low, alarm_high) -> str:
    if alarm_low is not None and value < alarm_low:
        return "alarm"
    if alarm_high is not None and value > alarm_high:
        return "alarm"
    return "ok"


def update_sensor_status(
    conn: sqlite3.Connection,
    sensor_id: int,
    raw_value,
    scaled_value,
    state: str,
) -> None:
    ts = now_iso()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sensor_status
        (sensor_id, raw_value, scaled_value, state, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sensor_id) DO UPDATE SET
            raw_value = excluded.raw_value,
            scaled_value = excluded.scaled_value,
            state = excluded.state,
            updated_at = excluded.updated_at
    """, (sensor_id, raw_value, scaled_value, state, ts))

    cur.execute("""
        INSERT INTO sensor_history
        (sensor_id, raw_value, scaled_value, state, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (sensor_id, raw_value, scaled_value, state, ts))


def mark_sensor_error(
    conn: sqlite3.Connection,
    sensor_id: int,
) -> None:
    ts = now_iso()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sensor_status
        (sensor_id, raw_value, scaled_value, state, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sensor_id) DO UPDATE SET
            raw_value = excluded.raw_value,
            scaled_value = excluded.scaled_value,
            state = excluded.state,
            updated_at = excluded.updated_at
    """, (sensor_id, None, None, "error", ts))

    cur.execute("""
        INSERT INTO sensor_history
        (sensor_id, raw_value, scaled_value, state, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (sensor_id, None, None, "error", ts))


def mark_sensor_offline(
    conn: sqlite3.Connection,
    sensor_id: int,
) -> None:
    ts = now_iso()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sensor_status
        (sensor_id, raw_value, scaled_value, state, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sensor_id) DO UPDATE SET
            raw_value = excluded.raw_value,
            scaled_value = excluded.scaled_value,
            state = excluded.state,
            updated_at = excluded.updated_at
    """, (sensor_id, None, None, "offline", ts))


def ensure_db_exists() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")


def main() -> None:
    print("ADC Reader started")
    print(f"Using database: {DB_PATH}")

    ensure_db_exists()

    reader = MCP3204Reader(bus=0, device=0)
    loop_counter = 0

    try:
        while True:
            cycle_start = time.time()
            loop_counter += 1

            try:
                with get_db_connection() as conn:
                    sensor_configs = get_sensor_configs(conn)

                    for row in sensor_configs:
                        sensor_id = int(row["id"])
                        name = row["name"]
                        channel = int(row["channel"])
                        unit = row["unit"]
                        min_raw = float(row["min_raw"])
                        max_raw = float(row["max_raw"])
                        min_scaled = float(row["min_scaled"])
                        max_scaled = float(row["max_scaled"])
                        alarm_low = row["alarm_low"]
                        alarm_high = row["alarm_high"]
                        enabled = int(row["enabled"])

                        if not enabled:
                            mark_sensor_offline(conn, sensor_id)
                            continue

                        try:
                            raw = reader.read_channel(channel)
                            scaled = scale_value(raw, min_raw, max_raw, min_scaled, max_scaled)
                            state = calc_state(scaled, alarm_low, alarm_high)

                            update_sensor_status(conn, sensor_id, raw, scaled, state)

                            print(
                                f"[{loop_counter}] Sensor {sensor_id} ({name}) "
                                f"CH{channel} raw={raw} scaled={scaled:.3f} {unit} state={state}"
                            )

                        except Exception as sensor_error:
                            print(
                                f"[{loop_counter}] Sensor {sensor_id} ({name}) "
                                f"CH{channel} read error: {sensor_error}"
                            )
                            mark_sensor_error(conn, sensor_id)

                    conn.commit()

            except Exception as cycle_error:
                print(f"[{loop_counter}] Cycle error: {cycle_error}")
                traceback.print_exc()

                try:
                    print("Trying SPI reconnect...")
                    reader.reconnect()
                    print("SPI reconnect successful")
                except Exception as reconnect_error:
                    print(f"SPI reconnect failed: {reconnect_error}")

            elapsed = time.time() - cycle_start
            sleep_time = max(0.0, 1.0 - elapsed)
            time.sleep(sleep_time)

    finally:
        reader.close()


if __name__ == "__main__":
    main()