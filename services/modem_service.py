from __future__ import annotations

import re
import subprocess
from typing import Any

from config import MODEM_INDEX
from db import connection


class ModemError(RuntimeError):
    pass



def run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
        return result.stdout.strip()
    except FileNotFoundError as exc:
        raise ModemError(f"Befehl nicht gefunden: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip() or "unbekannter Fehler"
        raise ModemError(error) from exc
    except subprocess.TimeoutExpired as exc:
        raise ModemError("Timeout beim Lesen des Modems") from exc



def get_modem_config() -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM modem_config WHERE id = 1").fetchone()
        return dict(row)



def update_modem_config(data: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE modem_config
            SET apn = ?, pin = ?, preferred_mode = ?, auto_connect = ?, roaming_allowed = ?
            WHERE id = 1
            """,
            (
                data.get("apn", "internet"),
                data.get("pin", ""),
                data.get("preferred_mode", "auto"),
                int(bool(data.get("auto_connect"))),
                int(bool(data.get("roaming_allowed"))),
            ),
        )



def _parse_key_value_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = re.sub(r"\s+", " ", left).strip().lower().replace(" ", "_")
        result[key] = right.strip()
    return result



def get_modem_status() -> dict[str, Any]:
    config = get_modem_config()
    try:
        output = run_command(["mmcli", "-m", str(MODEM_INDEX)])
        parsed = _parse_key_value_output(output)
        return {
            "available": True,
            "error": None,
            "operator": parsed.get("operator_name", "unbekannt"),
            "signal_quality": parsed.get("signal_quality", "unbekannt"),
            "access_tech": parsed.get("access_technologies", parsed.get("current_capabilities", "unbekannt")),
            "registration_state": parsed.get("state", "unbekannt"),
            "sim_state": parsed.get("unlock_required", "ready"),
            "apn": config.get("apn", "internet"),
            "preferred_mode": config.get("preferred_mode", "auto"),
            "auto_connect": bool(config.get("auto_connect", 0)),
            "roaming_allowed": bool(config.get("roaming_allowed", 0)),
        }
    except ModemError as exc:
        return {
            "available": False,
            "error": str(exc),
            "operator": "-",
            "signal_quality": "-",
            "access_tech": "-",
            "registration_state": "offline",
            "sim_state": "unknown",
            "apn": config.get("apn", "internet"),
            "preferred_mode": config.get("preferred_mode", "auto"),
            "auto_connect": bool(config.get("auto_connect", 0)),
            "roaming_allowed": bool(config.get("roaming_allowed", 0)),
        }



def connect_modem() -> str:
    config = get_modem_config()
    apn = config.get("apn", "internet")
    output = run_command(["mmcli", "-m", str(MODEM_INDEX), "--simple-connect", f"apn={apn}"])
    return output or "Modem verbunden"



def disconnect_modem() -> str:
    output = run_command(["mmcli", "-m", str(MODEM_INDEX), "--simple-disconnect"])
    return output or "Modem getrennt"
