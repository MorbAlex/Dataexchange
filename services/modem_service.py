import os
import re
import subprocess
from db import fetch_one, execute, now_iso

WWAN_IFACE = os.getenv("WWAN_IFACE", "wwan0")
MODEM_ID = os.getenv("MODEM_ID", "0")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _update_runtime(status=None, error=None, packet_data_handle=None, last_ip=None):
    current = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")

    execute(
        '''
        UPDATE modem_runtime
        SET packet_data_handle=?, last_ip=?, last_status=?, last_error=?, updated_at=?
        WHERE id=1
        ''',
        (
            packet_data_handle if packet_data_handle is not None else current["packet_data_handle"],
            last_ip if last_ip is not None else current["last_ip"],
            status if status is not None else current["last_status"],
            error if error is not None else current["last_error"],
            now_iso(),
        )
    )


def _get_iface_ip():
    rc, out, _ = _run(["ip", "-4", "addr", "show", WWAN_IFACE])
    if rc != 0:
        return ""

    match = re.search(r"inet\s+([0-9.]+)", out)
    return match.group(1) if match else ""


def _recover_modem():
    _run(["mmcli", "-m", str(MODEM_ID), "--disable"])
    _run(["mmcli", "-m", str(MODEM_ID), "--enable"])


def get_modem_status():
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    runtime = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")

    status = {
        "present": False,
        "operator": "-",
        "access_tech": "-",
        "signal_quality": "-",
        "registration_state": "-",
        "sim_state": "-",
        "ip_address": runtime["last_ip"] if runtime else "",
        "runtime_status": runtime["last_status"] if runtime else "unknown",
        "last_error": runtime["last_error"] if runtime else "",
        "packet_data_handle": runtime["packet_data_handle"] if runtime else "",
        "apn": config["apn"] if config else "internet",
        "preferred_mode": config["preferred_mode"] if config else "auto",
        "auto_connect": config["auto_connect"] if config else 0,
        "roaming_allowed": config["roaming_allowed"] if config else 0,
    }

    rc, out, err = _run(["mmcli", "-m", str(MODEM_ID)])
    if rc != 0:
        status["last_error"] = err or out or "Modem nicht verfügbar"
        return status

    status["present"] = True

    for line in out.splitlines():
        s = line.strip()

        if "signal quality" in s and "|" in s:
            status["signal_quality"] = s.split("|", 1)[1].strip()

        elif "operator name" in s and "|" in s:
            status["operator"] = s.split("|", 1)[1].strip()

        elif "access tech" in s and "|" in s:
            status["access_tech"] = s.split("|", 1)[1].strip()

        elif s.startswith("state") and "|" in s:
            status["registration_state"] = s.split("|", 1)[1].strip()

        elif "SIM" in s and "|" in s:
            status["sim_state"] = s.split("|", 1)[1].strip()

    ip_addr = _get_iface_ip()
    if ip_addr:
        status["ip_address"] = ip_addr
        _update_runtime(last_ip=ip_addr)

    return status


def connect_modem():
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    apn = config["apn"] if config else "internet"

    rc, out, err = _run([
        "mmcli",
        "-m",
        str(MODEM_ID),
        f"--simple-connect=apn={apn}"
    ])

    if rc != 0:
        _recover_modem()

        rc, out, err = _run([
            "mmcli",
            "-m",
            str(MODEM_ID),
            f"--simple-connect=apn={apn}"
        ])

    if rc != 0:
        message = err or out or "Verbindung fehlgeschlagen"
        _update_runtime(status="connect_failed", error=message)
        return False, f"Verbinden fehlgeschlagen: {message}"

    ip_addr = _get_iface_ip()

    _update_runtime(
        status="connected",
        error="",
        packet_data_handle="",
        last_ip=ip_addr,
    )

    return True, f"Modem verbunden. IP: {ip_addr or 'unbekannt'}"


def disconnect_modem():
    rc, out, err = _run([
        "mmcli",
        "-m",
        str(MODEM_ID),
        "--simple-disconnect"
    ])

    if rc != 0:
        message = err or out or "Trennen fehlgeschlagen"
        _update_runtime(status="disconnect_failed", error=message)
        return False, f"Trennen fehlgeschlagen: {message}"

    _run(["ip", "link", "set", WWAN_IFACE, "down"])
    _run(["ip", "link", "set", WWAN_IFACE, "up"])

    _update_runtime(
        status="disconnected",
        error="",
        packet_data_handle="",
        last_ip="",
    )

    return True, "Modem getrennt."