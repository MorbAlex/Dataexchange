import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from db import init_db, fetch_all, execute, now_iso, fetch_one

UPLOAD_URL = os.getenv("UPLOAD_URL", "http://10.178.164.33:8000/ingest")  # Beispiel: "http://example.com/ingest"
UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")

def post_json(url, payload, token=""):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read().decode("utf-8", errors="ignore")

def update_runtime(status="", error=""):
    execute(
        '''
        UPDATE upload_runtime
        SET last_upload_at=?, last_upload_status=?, last_upload_error=?, updated_at=?
        WHERE id=1
        ''',
        (now_iso(), status, error, now_iso())
    )

def main():
    init_db()
    if not UPLOAD_URL:
        print("UPLOAD_URL ist nicht gesetzt.")
        update_runtime("disabled", "UPLOAD_URL ist nicht gesetzt")
        return

    print("Uploader gestartet.")
    while True:
        rows = fetch_all(
            '''
            SELECT h.id, h.sensor_id, h.raw_value, h.scaled_value, h.state, h.created_at, c.name, c.unit
            FROM sensor_history h
            JOIN sensor_config c ON c.id = h.sensor_id
            WHERE h.uploaded = 0
            ORDER BY h.id DESC
            LIMIT 100
            '''
        )

        rows = list(reversed(rows))

        if not rows:
            time.sleep(5)
            continue

        payload = {
            "device": "cm5-prototype",
            "records": [
                {
                    "id": r["id"],
                    "sensor_id": r["sensor_id"],
                    "sensor_name": r["name"],
                    "raw_value": r["raw_value"],
                    "scaled_value": r["scaled_value"],
                    "unit": r["unit"],
                    "state": r["state"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        }

        try:
            status, body = post_json(UPLOAD_URL, payload, UPLOAD_TOKEN)
            if 200 <= status < 300:
                ids = ",".join(str(r["id"]) for r in rows)
                execute(f"UPDATE sensor_history SET uploaded = 1 WHERE id IN ({ids})")
                update_runtime("ok", "")
                print(f"{len(rows)} Datensätze hochgeladen.")
            else:
                update_runtime("http_error", f"HTTP {status}: {body}")
                print(f"Upload fehlgeschlagen: HTTP {status}")
        except urllib.error.URLError as e:
            update_runtime("network_error", str(e))
            print(f"Netzwerkfehler: {e}")
        except Exception as e:
            update_runtime("error", str(e))
            print(f"Fehler: {e}")

        time.sleep(5)

if __name__ == "__main__":
    main()
