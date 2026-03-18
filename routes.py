from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import fetch_all, fetch_one, execute, now_iso
from services.modem_service import get_modem_status, connect_modem, disconnect_modem

bp = Blueprint("main", __name__)

def get_sensor_rows():
    return fetch_all(
        '''
        SELECT c.*, s.raw_value, s.scaled_value, s.state, s.updated_at
        FROM sensor_config c
        LEFT JOIN sensor_status s ON s.sensor_id = c.id
        ORDER BY c.id
        '''
    )

@bp.route("/")
def dashboard():
    sensors = get_sensor_rows()
    modem_status = get_modem_status()
    upload_runtime = fetch_one("SELECT * FROM upload_runtime WHERE id = 1")
    return render_template("dashboard.html", sensors=sensors, modem=modem_status, upload_runtime=upload_runtime)

@bp.route("/sensors/chart/<int:sensor_id>")
def sensor_chart(sensor_id):

    rows = fetch_all(
        """
        SELECT scaled_value, created_at
        FROM sensor_history
        WHERE sensor_id = ?
        ORDER BY id DESC
        LIMIT 100
        """,
        (sensor_id,)
    )

    sensor = fetch_one(
        "SELECT * FROM sensor_config WHERE id = ?",
        (sensor_id,)
    )

    rows = list(reversed(rows))

    labels = [r["created_at"] for r in rows]
    values = [r["scaled_value"] for r in rows]

    return render_template(
        "sensor_chart.html",
        sensor=sensor,
        labels=labels,
        values=values
    )

@bp.route("/sensors/status")
def sensor_status():
    return render_template("sensor_status.html", sensors=get_sensor_rows())

@bp.route("/sensors/config", methods=["GET", "POST"])
def sensor_config():
    if request.method == "POST":
        for sensor_id in range(1, 5):
            prefix = f"sensor_{sensor_id}_"
            execute(
                '''
                UPDATE sensor_config
                SET name=?, enabled=?, channel=?, unit=?, min_raw=?, max_raw=?, min_scaled=?, max_scaled=?,
                    alarm_low=?, alarm_high=?, sample_interval_ms=?, updated_at=?
                WHERE id=?
                ''',
                (
                    request.form.get(prefix + "name", f"Sensor {sensor_id}"),
                    1 if request.form.get(prefix + "enabled") == "on" else 0,
                    int(request.form.get(prefix + "channel", sensor_id - 1)),
                    request.form.get(prefix + "unit", "V"),
                    float(request.form.get(prefix + "min_raw", 0)),
                    float(request.form.get(prefix + "max_raw", 4095)),
                    float(request.form.get(prefix + "min_scaled", 0)),
                    float(request.form.get(prefix + "max_scaled", 10)),
                    float(request.form.get(prefix + "alarm_low", 0)),
                    float(request.form.get(prefix + "alarm_high", 10)),
                    int(request.form.get(prefix + "sample_interval_ms", 1000)),
                    now_iso(),
                    sensor_id,
                )
            )
        flash("Sensor-Konfiguration gespeichert.", "success")
        return redirect(url_for("main.sensor_config"))
    return render_template("sensor_config.html", sensors=get_sensor_rows())

@bp.route("/modem/status")
def modem_status():
    return render_template("modem_status.html", modem=get_modem_status())

@bp.route("/modem/config", methods=["GET", "POST"])
def modem_config():
    if request.method == "POST":
        execute(
            '''
            UPDATE modem_config
            SET apn=?, pin=?, auto_connect=?, preferred_mode=?, roaming_allowed=?, updated_at=?
            WHERE id=1
            ''',
            (
                request.form.get("apn", "internet"),
                request.form.get("pin", ""),
                1 if request.form.get("auto_connect") == "on" else 0,
                request.form.get("preferred_mode", "auto"),
                1 if request.form.get("roaming_allowed") == "on" else 0,
                now_iso(),
            )
        )
        flash("Modem-Konfiguration gespeichert.", "success")
        return redirect(url_for("main.modem_config"))
    config = fetch_one("SELECT * FROM modem_config WHERE id = 1")
    runtime = fetch_one("SELECT * FROM modem_runtime WHERE id = 1")
    return render_template("modem_config.html", config=config, runtime=runtime)

@bp.post("/modem/connect")
def modem_connect():
    ok, message = connect_modem()
    flash(message, "success" if ok else "error")
    return redirect(url_for("main.modem_status"))

@bp.post("/modem/disconnect")
def modem_disconnect():
    ok, message = disconnect_modem()
    flash(message, "success" if ok else "error")
    return redirect(url_for("main.modem_status"))
