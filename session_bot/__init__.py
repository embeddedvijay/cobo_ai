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
        # Full per-input-group rules come from the desktop JSON. The old
        # "name ^ LD" array remains supported as a fallback only.
        self.contact_rules = session_data.get("contact_rules", {}) or {}
        self.contact_director = {}
        for contact in session_data.get("in_contacts", []):
            name = _contact_name(contact)
            rate = str(contact).split("^", 1)[1].strip() if "^" in str(contact) else "100"
            rule = dict(self.contact_rules.get(name, {}) or {})
            rule.setdefault("LD", int(rate))
            rule.setdefault("Limit", 0)
            rule.setdefault("instant_cutting", False)
            rule.setdefault("Director", {})
            rule.setdefault("win_rate", {})
            self.contact_director[name] = rule

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

    def rule_for(self, contact: str) -> dict:
        return self.contact_director.get(_contact_name(contact), {})

    def _base_market(self, market: str) -> str:
        return str(market).rsplit("_", 1)[0]

    def director_target(self, contact: str, market: str, kind: str) -> str | None:
        """Market override wins; otherwise use this customer's all-market route.

        Desktop workspace owns customer routing. Reference JSON supplies only
        market defaults/timings, never customer destinations. Therefore only
        the explicit desktop `market_overrides` map is considered here; old
        top-level per-market Director entries such as ALL_MARKET are ignored.
        """
        director = self.rule_for(contact).get("Director", {})
        base = self._base_market(market)
        overrides = director.get("market_overrides", {})
        row = overrides.get(base, {}) or {}
        default_key = "all_table" if kind == "table" else "all_fast_forward"
        return row.get(kind) or director.get(default_key)

    def table_routes_for_market(self, market: str) -> dict:
        """Output target -> only its customers, so LD never leaks across groups."""
        routes = {}
        for contact in self.customer_contacts:
            # A formatted LD-cut table prefers All Table.  When the operator
            # has configured only Fast Forward for this customer, use it as a
            # safe fallback instead of silently dropping the table.
            target = self.director_target(contact, market, "table") or self.director_target(contact, market, "fast_forward")
            if target:
                routes.setdefault(str(target), []).append(contact)
        return routes

    def is_instant_cutting(self, contact: str) -> bool:
        return bool(self.rule_for(contact).get("instant_cutting", False))

    def should_send_reply(self, contact: str, reply_type: str | None) -> bool:
        """Apply an input group's reply setting; old configs default ON."""
        if not reply_type:
            return True
        settings = self.rule_for(contact).get("reply_settings", {}) or {}
        return bool(settings.get(reply_type, True))

    def format_ld_table(self, market: str, result_list: list, ld_value) -> tuple[str, int, dict]:
        # Match the legacy scheduler rounding: int(amount * LD / 100).
        try:
            rate = int(ld_value)
        except (TypeError, ValueError):
            rate = 100
        rows, bets, total = [], {}, 0
        for row in result_list or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                amount = int(row[-1])
            except (TypeError, ValueError):
                continue
            cut = int(amount * rate / 100)
            if cut <= 0:
                continue
            key = "=".join(str(part) for part in row[:-1])
            rows.append(f"*{key}={cut}*")
            bets[key] = bets.get(key, 0) + cut
            total += cut
        return "\n".join([f"*{market}*", *rows, f"*TOTAL={total}*"]), total, bets

    def forward_unparsed(self, contact: str, market: str | None, text: str) -> bool:
        # Instant Cutting customers must never receive the raw source message
        # in an output group. Their only delivery is the calculated LD table.
        if self.is_instant_cutting(contact):
            print(f"Instant route: raw forward suppressed for {contact}/{market or 'unknown'}", flush=True)
            return False
        target = self.director_target(contact, market, "fast_forward") if market else None
        if not target:
            # A no-market message has no per-market Director. Forward only when
            # this customer has exactly one safe fallback target.
            targets = {
                str(row.get("fast_forward")) for row in self.rule_for(contact).get("Director", {}).values()
                if row.get("fast_forward")
            }
            target = next(iter(targets)) if len(targets) == 1 else None
        if not target:
            print(f"No unambiguous fast_forward target for {contact}/{market or 'unknown'}", flush=True)
            return False
        self.send_message_to(target, text, priority=70)
        return True

    def forward_valid_play(self, contact: str, market: str, text: str) -> bool:
        """Send a valid accepted input directly only when this rule has a Fast Forward destination."""
        if self.is_instant_cutting(contact):
            print(f"Instant route: direct forward suppressed for {contact}/{market}", flush=True)
            return False
        target = self.director_target(contact, market, "fast_forward")
        if not target:
            return False
        self.send_message_to(target, text, market=market, priority=75)
        return True

    def send_instant_table(self, contact: str, market: str, result_list: list) -> bool:
        target = self.director_target(contact, market, "table") or self.director_target(contact, market, "fast_forward")
        if not target:
            print(f"No Table or Fast Forward destination for {contact}/{market}; immediate LD table skipped", flush=True)
            return False
        text, total, bets = self.format_ld_table(market, result_list, self.rule_for(contact).get("LD", 100))
        if total <= 0:
            return False
        self.send_message_to(
            target, text, market=market,
            settlement_payload={"bets": bets, "total_play": total, "source_contact": contact},
            priority=100,
        )
        print(f"Instant LD table queued: {contact}/{market} -> {target}; total={total}", flush=True)
        return True

    def notify_limit_once(self, contact: str) -> bool:
        try:
            from .db_ops import claim_limit_notice
            limit = int(self.rule_for(contact).get("Limit", 0) or 0)
            if claim_limit_notice(self.client_name, contact, limit):
                self.send_message_to(contact, "*LIMIT CHECK*", priority=90)
                return True
        except Exception as exc:
            print(f"Limit notification check failed for {contact}: {exc}", flush=True)
        return False

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
        self.last_reply_type = None
        # No recognised market means no valid HLA/DB operation. It may still be
        # forwarded only when this customer's Director has one clear destination.
        from .reply_processor import format_check
        if not format_check(text, self.client_name):
            self.forward_unparsed(contact, None, text)
            return "", 0
        return self.reply(text, contact, message_id)
