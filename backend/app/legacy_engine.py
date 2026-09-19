from __future__ import annotations

import threading
import unicodedata
import re

from session_bot import Session
from session_bot.constant import cancel_strings, invalid_format_reply

from .database import db
from .settings import find_session


class LegacyEngine:
    """Connects the unchanged legacy Reply_processor to durable raw/outbox state."""

    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], Session] = {}
        self.session_locks: dict[tuple[str, str], threading.RLock] = {}
        self.source_locks: dict[tuple[str, str, str], threading.RLock] = {}
        self.parallel_limits: dict[tuple[str, str], threading.BoundedSemaphore] = {}

    def get_session(self, client_name: str, session_name: str) -> Session:
        key = (client_name, session_name)
        if key not in self.sessions:
            meta = find_session(client_name, session_name)

            def outbox(target: str, text: str, *, kind: str = "legacy_output", market: str | None = None, settlement_payload: dict | None = None, priority: int = 50, business_date: str | None = None):
                db.enqueue({
                    "client_name": client_name, "session_name": session_name,
                    "channel": "whatsapp", "target": target, "text": text,
                    "quote": None, "kind": kind, "raw_id": None,
                    "market": market, "settlement_payload": settlement_payload,
                    "priority": priority, "business_date": business_date,
                })

            self.sessions[key] = Session(client_name, meta["client"].get("dynamic_timing", {}), meta["client"]["fixed_market_time"], meta["session"], outbox)
            self.session_locks[key] = threading.RLock()
            max_workers = max(1, int(meta["session"].get("processing", {}).get("max_parallel_sources", 4)))
            self.parallel_limits[key] = threading.BoundedSemaphore(max_workers)
        return self.sessions[key]

    @staticmethod
    def _is_cancel(text: str) -> bool:
        """Accept only the fixed cancel formats, with harmless typing cleanup.

        This accepts spaces between ❌ characters and CANCEL with final . or !,
        but intentionally rejects extra words such as 'cancel this'.
        """
        value = unicodedata.normalize("NFKC", str(text or "")).upper().replace("\ufe0f", "")
        compact = re.sub(r"\s+", "", value)
        emoji_commands = {
            re.sub(r"\s+", "", unicodedata.normalize("NFKC", command).replace("\ufe0f", ""))
            for command in cancel_strings if "❌" in command
        }
        if compact in emoji_commands:
            return True
        word_commands = {command.upper() for command in cancel_strings if command.isascii()}
        return bool(re.fullmatch(r"(?:" + "|".join(map(re.escape, word_commands)) + r")[.!]?", value.strip()))

    @staticmethod
    def _looks_like_cancel(text: str) -> bool:
        value = unicodedata.normalize("NFKC", str(text or "")).upper()
        return "CANCEL" in value or "❌" in value

    @staticmethod
    def _wrong_cancel_format() -> tuple[str, int]:
        return "*❌ Wrong cancel format*\nOriginal play message पर reply करके केवल ❌ या CANCEL भेजें।", 1

    def _process_cancel(self, session: Session, raw: dict) -> tuple[str, int]:
        """Recreate the old web_bot reply behavior without browser DOM access.

        Old Selenium read the message quoted by ❌/CANCEL, appended `CANCEL`,
        and passed that reconstructed play to Reply_processor. Baileys gives
        the quoted content directly in contextInfo, so cancellation reaches the
        same HLA and MongoDB negative-entry/cancel_check path.
        """
        target = db.cancel_target(
            raw["client_name"], raw["session_name"], raw["source_jid"], str(raw.get("quoted_message_id") or ""),
        )
        # A malformed input already received '*Pls Check MSG*'. Do not parse
        # it a second time: close that invalid record and acknowledge deletion.
        if target and invalid_format_reply in str(target.get("legacy_reply") or ""):
            if db.mark_invalid_raw_cancelled(target["_id"], raw["message_id"]):
                db.delete_invalid_legacy_record(target["_id"])
                return "*❌ Message Deleted*", 1
            return "*ℹ️ Message was already deleted*", 1

        # Prefer the durable original raw text even when the customer replied
        # to the bot acknowledgement. Fall back to quote text for old records
        # that predate raw/outbox linkage.
        original_text = str((target or {}).get("text") or raw.get("quoted_text") or "").strip()
        if not original_text:
            return self._wrong_cancel_format()
        return session.process_incoming(f"{original_text}\nCANCEL", raw["source_name"], raw["message_id"])

    def process_one(self, raw: dict) -> dict:
        key = (raw["client_name"], raw["session_name"])
        # Session construction/scheduler setup happens once. After that each
        # source JID owns a lock, while different groups use parallel slots.
        with self.session_locks.setdefault(key, threading.RLock()):
            session = self.get_session(*key)
        source_key = (*key, raw["source_jid"])
        source_lock = self.source_locks.setdefault(source_key, threading.RLock())
        with self.parallel_limits[key], source_lock:
            if self._is_cancel(raw["text"]):
                reply, _reply_flag = self._process_cancel(session, raw)
            elif self._looks_like_cancel(raw["text"]):
                reply, _reply_flag = self._wrong_cancel_format()
            else:
                reply, _reply_flag = session.process_incoming(raw["text"], raw["source_name"], raw["message_id"])
        if reply:
            # Every valid live input receives its acknowledgement immediately
            # on top of that exact WhatsApp message. raw_message contains the
            # original Baileys key + message required for native quoted reply.
            db.mark_raw(raw["_id"], "processed", normal_state="processed", legacy_reply=str(reply))
            db.enqueue({
                "client_name": raw["client_name"], "session_name": raw["session_name"],
                "channel": "whatsapp", "target": raw["source_jid"], "text": str(reply),
                "quote": raw["raw_message"], "kind": "normal_source_reply", "raw_id": raw["_id"],
                "priority": 60, "business_date": raw["business_date"],
            })
            return {"status": "processed", "reply": str(reply)}
        # The legacy processor may forward/table-send without returning a direct
        # acknowledgement. Such a message has no text available for final quote mode.
        db.mark_raw(raw["_id"], "processed", normal_state="processed", final_reply_state="skipped")
        return {"status": "processed"}


engine = LegacyEngine()
