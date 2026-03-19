import os
import re
import subprocess
import time

from db import fetch_one, execute, now_iso


WWAN_IFACE = os.getenv("WWAN_IFACE", "wwan0")
DEFAULT_MODEM_ID = os.getenv("MODEM_ID", "0")
MMCLI_BIN = os.getenv("MMCLI_BIN", "mmcli")
IP_BIN = os.getenv("IP_BIN", "ip")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def _update_runtime(status=None, error=None, packet_data_handle=None, last_ip=None):
    current = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")

    if current is None:
        return

    execute(
        """
        UPDATE modem_runtime
        SET packet_data_handle=?, last_ip=?, last_status=?, last_error=?, updated_at=?
        WHERE id=1
        """,
        (
            packet_data_handle if packet_data_handle is not None else current["packet_data_handle"],
            last_ip if last_ip is not None else current["last_ip"],
            status if status is not None else current["last_status"],
            error if error is not None else current["last_error"],
            now_iso(),
        ),
    )


def _get_iface_ip():
    rc, out, _ = _run([IP_BIN, "-4", "addr", "show", WWAN_IFACE])
    if rc != 0:
        return ""

    match = re.search(r"inet\s+([0-9.]+)", out)
    return match.group(1) if match else ""


def _find_modem_id():
    """
    Sucht die aktuelle Modem-ID dynamisch.
    Beispiel mmcli -L:
      /org/freedesktop/ModemManager1/Modem/0 [Quectel] RM500Q-GL
    """
    rc, out, err = _run([MMCLI_BIN, "-L"])
    if rc != 0:
        return None

    modem_ids = []

    for line in out.splitlines():
        match = re.search(r"/Modem/(\d+)", line)
        if match:
            modem_ids.append(match.group(1))

    if not modem_ids:
        return None

    # Bevorzuge die ENV-ID, falls sie noch existiert
    if DEFAULT_MODEM_ID in modem_ids:
        return DEFAULT_MODEM_ID

    # Sonst nimm das erste gefundene Modem
    return modem_ids[0]


def _wait_for_modem(timeout=15, interval=1.0):
    start = time.time()

    while time.time() - start < timeout:
        modem_id = _find_modem_id()
        if modem_id is not None:
            return modem_id
        time.sleep(interval)

    return None


def _get_modem_id_or_raise():
    modem_id = _wait_for_modem()
    if modem_id is None:
        raise RuntimeError("Kein Modem von ModemManager gefunden")
    return modem_id


def _extract_bearer_path(text: str) -> str:
    match = re.search(
        r"(/org/freedesktop/ModemManager1/Bearer/\d+|/org/freedesktop/ModemManager1/Modem/\d+/Bearer/\d+)",
        text,
    )
    return match.group(1) if match else ""


def _list_bearers(modem_id):
    rc, out, err = _run([MMCLI_BIN, "-m", str(modem_id), "--list-bearers"])
    if rc != 0:
        return []

    bearers = []
    for line in out.splitlines():
        match = re.search(
            r"(/org/freedesktop/ModemManager1/Bearer/\d+|/org/freedesktop/ModemManager1/Modem/\d+/Bearer/\d+)",
            line,
        )
        if match:
            bearers.append(match.group(1))

    return bearers


def _delete_all_bearers(modem_id):
    for bearer in _list_bearers(modem_id):
        _run([MMCLI_BIN, "-b", bearer, "--disconnect"])
        _run([MMCLI_BIN, "-m", str(modem_id), f"--delete-bearer={bearer}"])


def _disable_enable_modem(modem_id):
    _run([MMCLI_BIN, "-m", str(modem_id), "--disable"])
    time.sleep(2)
    _run([MMCLI_BIN, "-m", str(modem_id), "--enable"])
    time.sleep(3)


def _reset_modem(modem_id):
    _run([MMCLI_BIN, "-m", str(modem_id), "--reset"])
    time.sleep(5)


def _recover_modem():
    """
    Versucht ein soft recovery:
    - aktuelle Modem-ID finden
    - disable/enable
    - danach Modem-ID neu suchen
    """
    modem_id = _find_modem_id()
    if modem_id is None:
        return _wait_for_modem()

    _disable_enable_modem(modem_id)
    return _wait_for_modem()


def _hard_recover_modem():
    """
    Härteres Recovery mit Reset.
    Danach die neue Modem-ID erneut suchen.
    """
    modem_id = _find_modem_id()
    if modem_id is None:
        return _wait_for_modem()

    _reset_modem(modem_id)
    return _wait_for_modem(timeout=20, interval=1.0)


def get_modem_status():
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    runtime = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")

    status = {
        "present": False,
        "modem_id": None,
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

    modem_id = _find_modem_id()
    if modem_id is None:
        status["last_error"] = "Modem nicht verfügbar"
        return status

    status["modem_id"] = modem_id

    rc, out, err = _run([MMCLI_BIN, "-m", str(modem_id)])
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

    modem_id = _find_modem_id()
    if modem_id is None:
        _update_runtime(status="connect_failed", error="Kein Modem gefunden")
        return False, "Verbinden fehlgeschlagen: Kein Modem gefunden"

    # Alte Bearer vorher wegräumen
    _delete_all_bearers(modem_id)

    rc, out, err = _run([MMCLI_BIN, "-m", str(modem_id), f"--create-bearer=apn={apn}"])

    if rc != 0:
        modem_id = _recover_modem()
        if modem_id is not None:
            _delete_all_bearers(modem_id)
            rc, out, err = _run([MMCLI_BIN, "-m", str(modem_id), f"--create-bearer=apn={apn}"])

    # Sonderfall: failed state -> hartes Recovery
    if rc != 0 and "failed state" in f"{out} {err}".lower():
        modem_id = _hard_recover_modem()
        if modem_id is not None:
            _delete_all_bearers(modem_id)
            rc, out, err = _run([MMCLI_BIN, "-m", str(modem_id), f"--create-bearer=apn={apn}"])

    if rc != 0:
        message = err or out or "Bearer konnte nicht erstellt werden"
        _update_runtime(status="connect_failed", error=message, packet_data_handle="", last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    bearer_path = _extract_bearer_path(out)
    if not bearer_path:
        message = f"Bearer-Pfad konnte nicht gelesen werden. Ausgabe: {out or err}"
        _update_runtime(status="connect_failed", error=message, packet_data_handle="", last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    rc, out, err = _run([MMCLI_BIN, "-b", bearer_path, "--connect"])
    if rc != 0:
        message = err or out or "Bearer-Verbindung fehlgeschlagen"
        _update_runtime(status="connect_failed", error=message, packet_data_handle=bearer_path, last_ip="")
        return False, f"Verbinden fehlgeschlagen: {message}"

    # Kurz warten, damit Interface/IP da sind
    time.sleep(2)
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

    modem_id = _find_modem_id()
    if modem_id is None:
        _update_runtime(
            status="disconnected",
            error="",
            packet_data_handle="",
            last_ip="",
        )
        return True, "Modem war bereits nicht verfügbar."

    if bearer_path:
        _run([MMCLI_BIN, "-b", bearer_path, "--disconnect"])
        _run([MMCLI_BIN, "-m", str(modem_id), f"--delete-bearer={bearer_path}"])
    else:
        _delete_all_bearers(modem_id)

    _run([IP_BIN, "link", "set", WWAN_IFACE, "down"])
    _run([IP_BIN, "link", "set", WWAN_IFACE, "up"])

    _update_runtime(
        status="disconnected",
        error="",
        packet_data_handle="",
        last_ip="",
    )

    return True, "Modem getrennt."