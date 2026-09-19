"""Original Dust processor/scheduler with Selenium replaced by a Baileys outbox.

All legacy operation files remain in this package: db_ops.py, constant.py,
reply_processor.py, dynamic handlers and schedule_task.py. The only removed
layer is session_bot/web_bot (Selenium read/click/write code).
"""
from __future__ import annotations

import datetime
import os
import re

from .constant import markets_timings
from .reply_processor import Reply_processor
from .schedule_task import Scheduler
from .startup_time_verification import verify_time
from .runtime_config import custom_market_timings


def _contact_name(value: str) -> str:
    return str(value).split("^", 1)[0].strip()


class Session(Reply_processor, Scheduler):
    """Keeps legacy business behaviour and sends every output to a durable callback."""

    def __init__(self, client_name: str, dynamic_timing: dict, fixed_market_time: str, session_data: dict, outbox_callback):
        self.client_name = client_name
        self.dynamic_timing = dynamic_timing or {}
        self.session_name = session_data["session_name"]
        self.session_data = session_data
        self.outbox_callback = outbox_callback
        self.image_folder = "./market_image_data/"
        os.makedirs(self.image_folder, exist_ok=True)
        # Desktop JSON supplies its own {MARKET_OP: [start, weekday, end]} map.
        # Existing YAML installations continue to use their named timing preset.
        configured_timings = custom_market_timings(session_data.get("market_timings"))
        self.markets_time = configured_timings or markets_timings[fixed_market_time]

        # Direct YAML config replaces the old hard-coded remote Config database.
        self.in_contacts = [_contact_name(contact) for contact in session_data.get("in_contacts", [])]
        self.customer_contacts = list(self.in_contacts)
        self.contact_director = {}
        for contact in session_data.get("in_contacts", []):
            name = _contact_name(contact)
            rate = str(contact).split("^", 1)[1].strip() if "^" in str(contact) else "100"
            self.contact_director[name] = {"LD": int(rate), "Forward": "Forward Others", "Table": "Table Others"}

        self.out_contacts = {}
        for section, mapping in session_data.get("out_contacts", {}).items():
            self.out_contacts[section] = {}
            for key, contacts in mapping.items():
                contacts = contacts if isinstance(contacts, list) else [contacts]
                selected = contacts[datetime.datetime.today().weekday() % len(contacts)] if contacts else None
                if not selected:
                    continue
                percent = re.findall(r"\d+", str(key))
                clean_key = "".join(re.findall(r"\D+", str(key))) or str(key)
                if section == "fast_forward" and clean_key == "image":
                    self.out_contacts[section][clean_key] = selected
                elif clean_key == "other":
                    for market in self.markets_time:
                        self.out_contacts[section].setdefault(market, selected)
                elif any(clean_key in market for market in self.markets_time):
                    for market in self.markets_time:
                        if clean_key in market:
                            self.out_contacts[section][market] = selected
                            if percent:
                                self.out_contacts[section][market + "per"] = percent[0]
                else:
                    self.out_contacts[section][clean_key] = selected

        self.play_win_trigger = session_data.get("play_win", False)
        if self.play_win_trigger:
            self.play_win_trigger = self.play_win_trigger["trigger"]
            self.out_contacts["play"] = session_data["play_win"]["play"]
            self.out_contacts["win"] = session_data["play_win"]["win"]
            self.in_contacts.append(self.play_win_trigger)
        self.testing = ""
        if not configured_timings:
            verify_time(client_name, fixed_market_time, self.dynamic_timing.get("status", False))
        else:
            print(f"[{self.session_name}] loaded {len(configured_timings)} market timings from desktop JSON", flush=True)

        # These are the original HLA/DB/scheduler classes; no browser is created.
        Reply_processor.__init__(self)
        Scheduler.__init__(self)
        print(f"[{self.session_name}] legacy processor ready; inputs={self.in_contacts}", flush=True)

    def send_message_to(self, number, message: str, *, market: str | None = None, settlement_payload: dict | None = None, priority: int = 50, business_date: str | None = None) -> None:
        """Legacy forward/table/play/win output -> durable Baileys outbox."""
        targets = number if isinstance(number, list) else [number]
        for target in targets:
            self.outbox_callback(
                str(target), self.clean_me(str(message)), kind="legacy_output",
                market=market, settlement_payload=settlement_payload,
                priority=priority, business_date=business_date,
            )

    def clean_me(self, message: str) -> str:
        """Former Selenium helper kept for legacy scheduler compatibility.

        Baileys sends actual newlines, so unlike the Selenium JavaScript path we
        deliberately keep \n as a real line break in WhatsApp output.
        """
        return str(message).replace("Forwarded", " ").replace("'", " ")

    def send_image_to(self, number, image_path: str, message: str) -> None:
        # The old image forwarding required Selenium DOM extraction. Keep the
        # operation visible instead of silently dropping it; add Baileys media
        # download/send here only when image source processing is enabled.
        print(f"Image output requested for {number}; text queued, media skipped: {image_path}", flush=True)
        self.send_message_to(number, message)

    def process_incoming(self, text: str, contact: str, message_id: str):
        """Original Reply_processor.reply() entry point used by the FastAPI bridge."""
        return self.reply(text, contact, message_id)
