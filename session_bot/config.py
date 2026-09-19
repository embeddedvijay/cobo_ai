"""Local YAML configuration adapter. No cloud MongoDB credentials or remote sync."""
from __future__ import annotations

from pathlib import Path
import os
import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_runtime_config() -> dict:
    path = Path(os.getenv("COBO_RUNTIME_CONFIG_PATH", str(ROOT / "config.yaml"))).expanduser()
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _client(client_name: str) -> dict:
    config = load_runtime_config()
    for client in config.get("clients", []):
        if client.get("client_name") == client_name:
            return client
    raise KeyError(f"Client not found in config.yaml: {client_name}")


def get_contacts(client_name: str) -> dict:
    contacts = {}
    for session in _client(client_name).get("sessions", []):
        for entry in session.get("in_contacts", []):
            name, _, rate = str(entry).partition("^")
            contacts[name.strip()] = {"LD": int(rate.strip() or 0), "Forward": "Forward Others", "Table": "Table Others"}
    return contacts


def get_contacts_table(client_name: str) -> dict:
    # Legacy scheduler uses this only in the optional send_table_web method.
    return {"all": list(get_contacts(client_name).keys())}


def connect_to_cluster():
    return None


def send_data(data: dict):
    # Original db_ops.add_data() calls this after local Market/<date> insertion.
    # Local persistence is already complete, so no external copy is performed.
    return False
