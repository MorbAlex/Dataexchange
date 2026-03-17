from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/gateway.db")
UPLOAD_URL = os.getenv("UPLOAD_URL", "http://example.com/api/sensors")
UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")
UPLOAD_INTERVAL_SECONDS = int(os.getenv("UPLOAD_INTERVAL_SECONDS", "10"))
ADC_INTERVAL_SECONDS = int(os.getenv("ADC_INTERVAL_SECONDS", "2"))
ADC_MODE = os.getenv("ADC_MODE", "simulated")
MODEM_INDEX = os.getenv("MODEM_INDEX", "0")
