from __future__ import annotations

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

import config
from db import init_db
from services.modem_service import (
    ModemError,
    connect_modem,
    disconnect_modem,
    get_modem_config,
    get_modem_status,
    update_modem_config,
)
from services.sensor_service import (
    get_all_sensor_configs,
    get_recent_history,
    get_sensor,
    get_sensor_statuses,
    update_sensor_config,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY

init_db()


@app.route("/")
def dashboard():
    sensors = get_sensor_statuses()
    modem = get_modem_status()
    return render_template("dashboard.html", sensors=sensors, modem=modem)


@app.route("/sensors/status")
def sensor_status():
    return render_template("sensor_status.html", sensors=get_sensor_statuses())


@app.route("/sensors/config", methods=["GET", "POST"])
def sensor_config():
    if request.method == "POST":
        sensor_id = int(request.form["sensor_id"])
        current = get_sensor(sensor_id)
        if not current:
            flash("Sensor nicht gefunden.", "error")
            return redirect(url_for("sensor_config"))

        data = {
            "name": request.form.get("name", current["name"]),
            "enabled": 1 if request.form.get("enabled") == "on" else 0,
            "channel": int(request.form.get("channel", current["channel"])),
            "unit": request.form.get("unit", current["unit"]),
            "min_raw": float(request.form.get("min_raw", current["min_raw"])),
            "max_raw": float(request.form.get("max_raw", current["max_raw"])),
            "min_scaled": float(request.form.get("min_scaled", current["min_scaled"])),
            "max_scaled": float(request.form.get("max_scaled", current["max_scaled"])),
            "alarm_low": _nullable_float(request.form.get("alarm_low")),
            "alarm_high": _nullable_float(request.form.get("alarm_high")),
            "sample_interval_ms": int(request.form.get("sample_interval_ms", current["sample_interval_ms"])),
        }
        update_sensor_config(sensor_id, data)
        flash(f"Sensor {sensor_id} gespeichert.", "success")
        return redirect(url_for("sensor_config"))

    return render_template("sensor_config.html", sensors=get_all_sensor_configs())


@app.route("/modem/status")
def modem_status():
    return render_template("modem_status.html", modem=get_modem_status())


@app.route("/modem/config", methods=["GET", "POST"])
def modem_config():
    if request.method == "POST":
        data = {
            "apn": request.form.get("apn", "internet"),
            "pin": request.form.get("pin", ""),
            "preferred_mode": request.form.get("preferred_mode", "auto"),
            "auto_connect": request.form.get("auto_connect") == "on",
            "roaming_allowed": request.form.get("roaming_allowed") == "on",
        }
        update_modem_config(data)
        flash("Modem-Konfiguration gespeichert.", "success")
        return redirect(url_for("modem_config"))

    return render_template("modem_config.html", modem_config=get_modem_config(), modem=get_modem_status())


@app.route("/modem/connect", methods=["POST"])
def modem_connect():
    target = request.form.get("return_to", "modem_status")
    try:
        flash(connect_modem(), "success")
    except ModemError as exc:
        flash(f"Verbinden fehlgeschlagen: {exc}", "error")
    return redirect(url_for(target))


@app.route("/modem/disconnect", methods=["POST"])
def modem_disconnect():
    target = request.form.get("return_to", "modem_status")
    try:
        flash(disconnect_modem(), "success")
    except ModemError as exc:
        flash(f"Trennen fehlgeschlagen: {exc}", "error")
    return redirect(url_for(target))


@app.route("/api/status")
def api_status():
    return jsonify({
        "sensors": get_sensor_statuses(),
        "modem": get_modem_status(),
        "history": get_recent_history(limit=20),
    })


@app.route("/health")
def health():
    return {"status": "ok"}



def _nullable_float(value: str | None):
    if value is None or value == "":
        return None
    return float(value)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
