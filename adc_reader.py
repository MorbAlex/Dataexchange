from __future__ import annotations

import math
import random
import time

from config import ADC_INTERVAL_SECONDS, ADC_MODE
from db import init_db
from services.sensor_service import get_all_sensor_configs, record_sensor_reading


class SimulatedAdcAdapter:
    def __init__(self) -> None:
        self.start = time.time()

    def read_channel(self, channel: int) -> float:
        base = (math.sin((time.time() - self.start) / 8 + channel) + 1) / 2
        noise = random.uniform(-0.04, 0.04)
        value = max(0.0, min(1.0, base + noise))
        return round(value * 1023, 2)


class RealAdcAdapter:
    def read_channel(self, channel: int) -> float:
        raise NotImplementedError(
            "Bitte RealAdcAdapter.read_channel() mit deinem ADC/Bus implementieren."
        )



def build_adapter():
    if ADC_MODE == "real":
        return RealAdcAdapter()
    return SimulatedAdcAdapter()



def main() -> None:
    init_db()
    adapter = build_adapter()
    print(f"ADC reader gestartet (mode={ADC_MODE}, interval={ADC_INTERVAL_SECONDS}s)")
    while True:
        configs = get_all_sensor_configs()
        for sensor in configs:
            if not sensor["enabled"]:
                continue
            raw = adapter.read_channel(int(sensor["channel"]))
            record_sensor_reading(int(sensor["id"]), raw)
            print(f"sensor={sensor['id']} raw={raw}")
        time.sleep(ADC_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
