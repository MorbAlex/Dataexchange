from __future__ import annotations

import time

import requests

from config import UPLOAD_INTERVAL_SECONDS, UPLOAD_TOKEN, UPLOAD_URL
from db import init_db
from services.sensor_service import get_unsent_history, mark_history_uploaded



def upload_batch() -> None:
    rows = get_unsent_history(limit=50)
    if not rows:
        print("Keine neuen Datensätze zum Senden.")
        return

    payload = {
        "device": "cm5-gateway",
        "measurements": rows,
    }
    headers = {"Content-Type": "application/json"}
    if UPLOAD_TOKEN:
        headers["Authorization"] = f"Bearer {UPLOAD_TOKEN}"

    response = requests.post(UPLOAD_URL, json=payload, headers=headers, timeout=20)
    response.raise_for_status()
    mark_history_uploaded([row["id"] for row in rows])
    print(f"{len(rows)} Datensätze hochgeladen.")



def main() -> None:
    init_db()
    print(f"Uploader gestartet -> {UPLOAD_URL}")
    while True:
        try:
            upload_batch()
        except Exception as exc:
            print(f"Upload fehlgeschlagen: {exc}")
        time.sleep(UPLOAD_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
