"""Settings that come from the environment: where things live, which port, which models."""
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo



ROOT = Path(__file__).resolve().parents[2]  # server/underwatch/config.py → the project root

WEB = ROOT / "web"

DATA = ROOT / "data"


DATA.mkdir(exist_ok=True)


DB_PATH = DATA / "mind.sqlite"

TZ = ZoneInfo(os.environ.get("RESIDENT_TZ", "Europe/Ljubljana"))

WAKE_H = int(os.environ.get("WAKE_HOUR", "8"))

SLEEP_H = int(os.environ.get("SLEEP_HOUR", "16"))

HOST = os.environ.get("HOST", "127.0.0.1")

PORT = int(os.environ.get("PORT", "8765"))

MODEL_FAST = os.environ.get("MODEL_FAST", "haiku")

MODEL_DEEP = os.environ.get("MODEL_DEEP", "sonnet")

TICK = 5  # seconds between mind-loop checks

PASSWORD = os.environ.get("PASSWORD", "")  # the first password; once it's changed in the settings, the stored one wins


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

OWNER_LOGIN = os.environ.get("OWNER_LOGIN", "mike")

TLS_DIR = DATA / "tls"
