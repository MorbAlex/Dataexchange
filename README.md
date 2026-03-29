# CM5 Python Prototype (QMI)

Python-only Prototyp für Raspberry Pi CM5 mit:

- Flask-Weboberfläche
- SQLite-Datenbank
- 5 Tabs:
  - Dashboard
  - Sensor Status
  - Sensor Konfiguration
  - Modem Status
  - Modem Konfiguration
- `adc_reader.py` als separates Python-Programm
- `uploader.py` als separates Python-Programm
- QMI-Verbindung für Quectel RM500/RM500Q via `qmicli`
- persistente Einstellungen in SQLite

## Requirements

- Python = 3.13.2
- Flask = 3.0.3
- python-dotenv = 1.0.1
- modemmanager
- libqmi-utils
- udhcpc
- screen

## Funktionen

### Sensoren
- 4 Sensor-Konfigurationen in SQLite
- aktueller Sensorstatus in SQLite
- Historie in SQLite
- ADC-Reader läuft separat und schreibt Werte in die DB
- Standardmäßig Simulationsmodus, bis echte ADC-Anbindung ergänzt wird

### Modem
- Status über `mmcli`
- Connect/Disconnect über `qmicli`
- IP-Zuweisung via `udhcpc`
- Konfiguration (APN, Auto-Connect, Roaming, bevorzugter Modus) in SQLite
- Runtime-Infos wie Packet Handle, IP und letzter Fehler in SQLite

## Voraussetzungen auf dem Raspberry

Zusätzlich zu Python-Paketen werden Systemtools benötigt:

```bash
sudo apt update
sudo apt install -y modemmanager libqmi-utils udhcpc screen
```

## Projekt starten

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Dann im Browser:

```text
http://<raspberry-ip>:8000
```

## ADC Reader starten

```bash
source .venv/bin/activate
python scripts/adc_reader.py
```

## Uploader starten

```bash
source .venv/bin/activate
python scripts/uploader.py
```

## Wichtige Hinweise

- Der ADC-Reader ist im Simulationsmodus sofort nutzbar.
- Für echte Hardware die Methode `read_all_channels()` in `scripts/adc_reader.py` anpassen.
- `qmicli` Connect/Disconnect speichert den `packet_data_handle` in der Tabelle `modem_runtime`.
- Die Datenbank liegt standardmäßig unter `data/app.db`.
- Einstellungen bleiben bei Absturz oder Reboot erhalten, weil sie in SQLite gespeichert werden.

## PIN speichern
Für einen Prototypen ist ein PIN-Feld vorhanden. Es wird derzeit **im Klartext in SQLite** gespeichert.
Für produktiven Einsatz sollte die PIN nicht unverschlüsselt gespeichert werden.

## Systemd
Beispieldateien liegen unter `systemd/`.
Die Pfade darin müssen an dein Zielsystem angepasst werden.

## Tabellen

- `sensor_config`
- `sensor_status`
- `sensor_history`
- `modem_config`
- `modem_runtime`
- `upload_runtime`
