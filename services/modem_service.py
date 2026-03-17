import os
import re
import subprocess
from db import fetch_one, execute, now_iso

QMI_DEVICE = os.getenv("QMI_DEVICE", "/dev/cdc-wdm0")
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
        elif s.startswith("SIM") and "|" in s:
            status["sim_state"] = s.split("|", 1)[1].strip()

    rc, out, _ = _run(["ip", "-4", "addr", "show", WWAN_IFACE])
    if rc == 0:
        m = re.search(r"inet\s+([0-9.]+)", out)
        if m:
            status["ip_address"] = m.group(1)
            _update_runtime(last_ip=m.group(1))
    return status

def connect_modem():
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    apn = config["apn"] if config else "internet"

    rc, out, err = _run([
        "qmicli", "-d", QMI_DEVICE, "--device-open-proxy",
        f"--wds-start-network=apn={apn}", "--client-no-release-cid"
    ])
    if rc != 0:
        message = err or out or "Verbindung fehlgeschlagen"
        _update_runtime(status="connect_failed", error=message)
        return False, f"Verbinden fehlgeschlagen: {message}"

    handle_match = re.search(r"Packet data handle:\s*'?(\d+)'?", out)
    handle = handle_match.group(1) if handle_match else ""
    _update_runtime(status="connected", error="", packet_data_handle=handle)

    rc2, out2, err2 = _run(["udhcpc", "-i", WWAN_IFACE, "-n", "-q"])
    if rc2 != 0:
        msg = err2 or out2 or "DHCP fehlgeschlagen"
        _update_runtime(status="dhcp_failed", error=msg)
        return False, f"Datenverbindung aktiv, aber DHCP fehlgeschlagen: {msg}"

    rc3, out3, _ = _run(["ip", "-4", "addr", "show", WWAN_IFACE])
    ip_match = re.search(r"inet\s+([0-9.]+)", out3)
    ip_addr = ip_match.group(1) if ip_match else ""
    _update_runtime(status="connected", error="", packet_data_handle=handle, last_ip=ip_addr)
    return True, f"Modem verbunden. IP: {ip_addr or 'unbekannt'}"

def disconnect_modem():
    runtime = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")
    handle = runtime["packet_data_handle"] if runtime else ""
    if not handle:
        _update_runtime(status="disconnected", error="", packet_data_handle="", last_ip="")
        return True, "Keine aktive QMI-Session gespeichert."

    rc, out, err = _run([
        "qmicli", "-d", QMI_DEVICE, "--device-open-proxy",
        f"--wds-stop-network={handle}"
    ])
    if rc != 0:
        message = err or out or "Trennen fehlgeschlagen"
        _update_runtime(status="disconnect_failed", error=message)
        return False, f"Trennen fehlgeschlagen: {message}"

    _run(["ip", "link", "set", WWAN_IFACE, "down"])
    _run(["ip", "link", "set", WWAN_IFACE, "up"])
    _update_runtime(status="disconnected", error="", packet_data_handle="", last_ip="")
    return True, "Modem getrennt."
