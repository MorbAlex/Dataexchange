import os
import math
import time
import random
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from db import init_db, fetch_all, execute, now_iso

class RealAdcAdapter:
    def read_all_channels(self):
        raise NotImplementedError("Bitte echte ADC-Logik in RealAdcAdapter ergänzen.")

class SimulatedAdcAdapter:
    def __init__(self):
        self.t0 = time.time()

    def read_all_channels(self):
        t = time.time() - self.t0
        return {
            0: 2000 + 1000 * math.sin(t / 10),
            1: 1500 + 800 * math.sin(t / 8 + 0.5),
            2: 500 + 400 * math.sin(t / 5 + 1.1),
            3: 3000 + 700 * math.sin(t / 12 + 2.2) + random.uniform(-50, 50),
        }

def scale_value(raw, min_raw, max_raw, min_scaled, max_scaled):
    if max_raw == min_raw:
        return min_scaled
    ratio = (raw - min_raw) / (max_raw - min_raw)
    return min_scaled + ratio * (max_scaled - min_scaled)

def calc_state(value, low, high):
    if value < low or value > high:
        return "alarm"
    margin = (high - low) * 0.1
    if value < low + margin or value > high - margin:
        return "warning"
    return "ok"

def main():
    init_db()
    mode = os.getenv("ADC_MODE", "sim")
    adapter = SimulatedAdcAdapter() if mode == "sim" else RealAdcAdapter()
    print(f"ADC reader gestartet. Modus: {mode}")

    while True:
        sensors = fetch_all("SELECT * FROM sensor_config ORDER BY id")
        raw_by_channel = adapter.read_all_channels()

        for s in sensors:
            if not s["enabled"]:
                raw = 0.0
                scaled = 0.0
                state = "disabled"
            else:
                raw = float(raw_by_channel.get(s["channel"], 0.0))
                scaled = scale_value(raw, s["min_raw"], s["max_raw"], s["min_scaled"], s["max_scaled"])
                state = calc_state(scaled, s["alarm_low"], s["alarm_high"])

            ts = now_iso()
            execute(
                '''
                UPDATE sensor_status
                SET raw_value=?, scaled_value=?, state=?, updated_at=?
                WHERE sensor_id=?
                ''',
                (raw, scaled, state, ts, s["id"])
            )
            execute(
                '''
                INSERT INTO sensor_history (sensor_id, raw_value, scaled_value, state, created_at, uploaded)
                VALUES (?, ?, ?, ?, ?, 0)
                ''',
                (s["id"], raw, scaled, state, ts)
            )

        interval_ms = min([s["sample_interval_ms"] for s in sensors]) if sensors else 1000
        time.sleep(max(interval_ms / 1000.0, 0.2))

if __name__ == "__main__":
    main()
