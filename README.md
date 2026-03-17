# CM5 Python Prototype

Python-only Prototyp für Raspberry Pi CM5 mit:
- Flask-Weboberfläche
- SQLite-Datenbank
- `adc_reader.py` als separates Python-Programm für 4 analoge Sensoren
- `uploader.py` als separates Python-Programm zum Senden an einen Server
- Modemstatus und Modemaktionen über `mmcli`
- 5 Hauptseiten in der Navigation

## Tabs / Seiten

- `Dashboard` – Überblick über Sensoren und Modem
- `Sensor Status` – aktuelle Messwerte aller 4 Sensoren
- `Sensor Konfiguration` – je Sensor eine eigene Konfigurationskarte
- `Modem Status` – aktueller Verbindungs- und SIM-Status
- `Modem Konfiguration` – APN, PIN, Auto Connect, Roaming, bevorzugter Modus

## Struktur

- `app.py` – Webserver
- `adc_reader.py` – Sensorwerte lesen und in DB schreiben
- `uploader.py` – neue Werte an externen Server senden
- `services/sensor_service.py` – Sensorlogik
- `services/modem_service.py` – Modemlogik
- `templates/` – HTML-Seiten
- `static/` – CSS
- `systemd/` – Service-Dateien

## Start lokal

```bash
cd cm5_python_prototype
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
python adc_reader.py
```

Standardmäßig läuft der Reader im Simulationsmodus.

Für echte Hardware:
- `.env` anpassen: `ADC_MODE=real`
- `RealAdcAdapter.read_channel()` in `adc_reader.py` implementieren

## Uploader starten

```bash
source .venv/bin/activate
python uploader.py
```

In `.env` konfigurieren:
- `UPLOAD_URL`
- optional `UPLOAD_TOKEN`

## Modem

Die Weboberfläche nutzt `mmcli`.
Dafür muss auf dem Raspberry installiert sein:

```bash
sudo apt update
sudo apt install modemmanager
```

Wenn `mmcli -m 0` funktioniert, kann die Weboberfläche Status anzeigen.

## systemd

Projekt nach `/opt/cm5_python_prototype` kopieren und Services aktivieren:

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cm5-web.service cm5-adc-reader.service cm5-uploader.service
sudo systemctl start cm5-web.service cm5-adc-reader.service cm5-uploader.service
```
