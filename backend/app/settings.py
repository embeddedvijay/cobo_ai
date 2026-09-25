from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def runtime_config_path() -> Path:
    """Desktop launch writes a JSON file (valid YAML) and passes this path."""
    value = os.getenv("COBO_RUNTIME_CONFIG_PATH")
    return Path(value).expanduser() if value else ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with runtime_config_path().open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def business_date(now=None) -> str:
    """Return the trading date used by both legacy Market collections and outbox.

    MAIN_BAZAR close may continue after 00:00.  The configurable rollover keeps
    that whole night in the previous trading day's collection instead of
    splitting its plays/results across two MongoDB collections.
    """
    from datetime import datetime, timedelta, time
    now = now or datetime.now()
    value = str(load_config().get("business_day_rollover", "04:00"))
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        rollover = time(hour, minute)
    except (TypeError, ValueError):
        rollover = time(4, 0)
    if now.time() < rollover:
        now -= timedelta(days=1)
    return now.strftime("%y-%m-%d")


def mongo_url() -> str:
    return os.getenv("MONGODB_URL", load_config().get("mongo", {}).get("url", "mongodb://127.0.0.1:27017/"))


def mongo_database() -> str:
    return os.getenv("MONGODB_DATABASE", load_config().get("mongo", {}).get("database", "Market"))


def bridge_secret() -> str:
    return os.getenv("BRIDGE_SECRET", "")


def find_session(client_name: str, session_name: str) -> dict:
    for client in load_config().get("clients", []):
        if client.get("client_name") != client_name:
            continue
        for session in client.get("sessions", []):
            if session.get("session_name") == session_name:
                return {"client": client, "session": session}
    raise KeyError(f"Unknown client/session: {client_name}/{session_name}")


def clean_contact(value: str) -> str:
    return str(value).split("^", 1)[0].strip()
