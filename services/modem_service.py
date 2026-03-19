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


def _extract_bearer_path(text: str) -> str:
    # Beispiel:
    # Successfully created new bearer in modem /org/freedesktop/ModemManager1/Modem/0/Bearer/1
    match = re.search(r'(/org/freedesktop/ModemManager1/Bearer/\d+|/org/freedesktop/ModemManager1/Modem/\d+/Bearer/\d+)', text)
    return match.group(1) if match else ""


def _list_bearers():
    rc, out, err = _run(["mmcli", "-m", str(MODEM_ID), "--list-bearers"])
    if rc != 0:
        return []

    bearers = []
    for line in out.splitlines():
        m = re.search(r'(/org/freedesktop/ModemManager1/Bearer/\d+|/org/freedesktop/ModemManager1/Modem/\d+/Bearer/\d+)', line)
        if m:
            bearers.append(m.group(1))
    return bearers


def _delete_all_bearers():
    for bearer in _list_bearers():
        _run(["mmcli", "-b", bearer, "--disconnect"])
        _run(["mmcli", "-m", str(MODEM_ID), f"--delete-bearer={bearer}"])


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
        "bearers": [],
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
        elif "bearers" in s and "|" in s:
            status["bearers"] = [x.strip() for x in s.split("|", 1)[1].split(",") if x.strip()]

    ip_addr = _get_iface_ip()
    if ip_addr:
        status["ip_address"] = ip_addr
        _update_runtime(last_ip=ip_addr)

    return status


def connect_modem():
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    apn = config["apn"] if config else "internet"

    # Alte Bearer wegräumen, damit wir keine verwaisten Sessions ansammeln
    _delete_all_bearers()

    rc, out, err = _run([
        "mmcli",
        "-m",
        str(MODEM_ID),
        f"--create-bearer=apn={apn}"
    ])

    if rc != 0:
        _recover_modem()
        rc, out, err = _run([
            "mmcli",
            "-m",
            str(MODEM_ID),
            f"--create-bearer=apn={apn}"
        ])

    if rc != 0:
        message = err or out or "Bearer konnte nicht erstellt werden"
        _update_runtime(status="connect_failed", error=message, packet_data_handle="", last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    bearer_path = _extract_bearer_path(out)
    if not bearer_path:
        message = f"Bearer-Pfad konnte nicht gelesen werden. Ausgabe: {out or err}"
        _update_runtime(status="connect_failed", error=message, packet_data_handle="", last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    rc, out, err = _run(["mmcli", "-b", bearer_path, "--connect"])
    if rc != 0:
        message = err or out or "Bearer-Verbindung fehlgeschlagen"
        _update_runtime(status="connect_failed", error=message, packet_data_handle=bearer_path, last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    ip_addr = _get_iface_ip()

    _update_runtime(
        status="connected",
        error="",
        packet_data_handle=bearer_path,
        last_ip=ip_addr,
    )

    return True, f"Modem verbunden. IP: {ip_addr or 'unbekannt'}"


def disconnect_modem():
    runtime = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")
    bearer_path = runtime["packet_data_handle"] if runtime else ""

    if bearer_path:
        _run(["mmcli", "-b", bearer_path, "--disconnect"])
        _run(["mmcli", "-m", str(MODEM_ID), f"--delete-bearer={bearer_path}"])
    else:
        # Fallback: alle Bearer sauber abbauen
        _delete_all_bearers()

    _run(["ip", "link", "set", WWAN_IFACE, "down"])
    _run(["ip", "link", "set", WWAN_IFACE, "up"])

    _update_runtime(
        status="disconnected",
        error="",
        packet_data_handle="",
        last_ip="",
    )

    return True, "Modem getrennt."