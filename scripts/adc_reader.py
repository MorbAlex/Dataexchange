import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import spidev


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "app.db"


class MCP3204Reader:
    def __init__(self, bus=0, device=0):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 1000000
        self.spi.mode = 0

    def read_channel(self, channel: int) -> int:
        if channel < 0 or channel > 3:
            raise ValueError("MCP3204 channel must be 0..3")

        cmd = [0x06, (channel & 0x03) << 6, 0x00]
        resp = self.spi.xfer2(cmd)

        value = ((resp[1] & 0x0F) << 8) | resp[2]
        return value

    def close(self):
        self.spi.close()


def scale_value(raw, min_raw, max_raw, min_scaled, max_scaled):
    if max_raw == min_raw:
        return min_scaled

    return min_scaled + ((raw - min_raw) / (max_raw - min_raw)) * (max_scaled - min_scaled)


def calc_state(value, alarm_low, alarm_high):
    if alarm_low is not None and value < alarm_low:
        return "alarm"

    if alarm_high is not None and value > alarm_high:
        return "alarm"

    return "ok"


def get_sensor_configs(conn):
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, channel, unit,
               min_raw, max_raw,
               min_scaled, max_scaled,
               alarm_low, alarm_high,
               enabled
        FROM sensor_config
        ORDER BY id
    """)

    return cur.fetchall()


def update_sensor_status(conn, sensor_id, raw, scaled, state):

    now = datetime.now(timezone.utc).isoformat()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sensor_status
        (sensor_id, raw_value, scaled_value, state, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sensor_id) DO UPDATE SET
            raw_value=excluded.raw_value,
            scaled_value=excluded.scaled_value,
            state=excluded.state,
            updated_at=excluded.updated_at
    """, (sensor_id, raw, scaled, state, now))

    cur.execute("""
        INSERT INTO sensor_history
        (sensor_id, raw_value, scaled_value, state, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (sensor_id, raw, scaled, state, now))

    conn.commit()


def main():

    print("ADC Reader started")
    print("Database:", DB_PATH)

    reader = MCP3204Reader()

    try:

        while True:

            conn = sqlite3.connect(DB_PATH)

            sensor_configs = get_sensor_configs(conn)

            for row in sensor_configs:

                (
                    sensor_id,
                    name,
                    channel,
                    unit,
                    min_raw,
                    max_raw,
                    min_scaled,
                    max_scaled,
                    alarm_low,
                    alarm_high,
                    enabled
                ) = row

                if not enabled:
                    continue

                try:

                    raw = reader.read_channel(channel)

                    scaled = scale_value(
                        raw,
                        min_raw,
                        max_raw,
                        min_scaled,
                        max_scaled
                    )

                    state = calc_state(
                        scaled,
                        alarm_low,
                        alarm_high
                    )

                    update_sensor_status(
                        conn,
                        sensor_id,
                        raw,
                        scaled,
                        state
                    )

                    print(
                        f"Sensor {sensor_id} CH{channel} "
                        f"raw={raw} scaled={scaled:.3f} {unit} state={state}"
                    )

                except Exception as e:

                    print(f"Sensor {sensor_id} read error:", e)

            conn.close()

            time.sleep(1)

    finally:
        reader.close()


if __name__ == "__main__":
    main()