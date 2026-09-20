from __future__ import annotations

from datetime import datetime, timedelta
import uuid
from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from .settings import business_date, mongo_database, mongo_url


class Database:
    """All durable state. Raw message payload is saved before any HLA processing."""

    def __init__(self) -> None:
        self.client = MongoClient(mongo_url(), tz_aware=True)
        self.db = self.client[mongo_database()]
        self.ensure_indexes()

    @property
    def date(self) -> str:
        return business_date()

    @property
    def raw(self):
        # One durable collection prevents a 00:50 date rollover from losing an
        # unfinished reply. business_date remains a field for daily searches.
        return self.db["whatsapp_raw_messages"]

    @property
    def outbox(self):
        return self.db["whatsapp_outbox"]

    @property
    def group_mappings(self):
        """Resolved WhatsApp group-name to JID mapping from the Baileys bridge."""
        return self.db["whatsapp_group_mappings"]

    @property
    def transactions(self):
        # Same Market/<YY-MM-DD> collection used by the legacy project.
        return self.db[self.date]

    def ensure_indexes(self) -> None:
        self.raw.create_index([("client_name", ASCENDING), ("session_name", ASCENDING), ("source_jid", ASCENDING), ("message_id", ASCENDING)], unique=True)
        self.raw.create_index([("state", ASCENDING), ("source_jid", ASCENDING), ("message_timestamp", ASCENDING), ("received_at", ASCENDING)])
        self.raw.create_index([("client_name", ASCENDING), ("session_name", ASCENDING), ("settlement_state", ASCENDING), ("message_timestamp", ASCENDING)])
        self.outbox.create_index([("client_name", ASCENDING), ("session_name", ASCENDING), ("state", ASCENDING), ("next_attempt_at", ASCENDING), ("priority", ASCENDING), ("created_at", ASCENDING)])
        self.outbox.create_index([("client_name", ASCENDING), ("session_name", ASCENDING), ("delivery_jid", ASCENDING), ("settlement_state", ASCENDING), ("created_at", ASCENDING)])
        # A final native reply is tied to one original WhatsApp message. This
        # makes clicking/repeating "last" safe even after a process restart.
        self.outbox.create_index("dedupe_key", unique=True, sparse=True)
        self.group_mappings.create_index(
            [("client_name", ASCENDING), ("session_name", ASCENDING), ("group_name_key", ASCENDING)],
            unique=True,
        )
        self.group_mappings.create_index(
            [("client_name", ASCENDING), ("session_name", ASCENDING), ("jid", ASCENDING)],
            unique=True,
        )
        self.transactions.create_index([("Client", ASCENDING), ("Contact", ASCENDING), ("Market", ASCENDING), ("Total", ASCENDING)])

        # A process kill can leave these transient states behind. The original
        # message/key is durable, so safe restart is to retry them, never drop them.
        self.raw.update_many({"state": "processing"}, {"$set": {"state": "received", "recovered_after_restart": datetime.utcnow()}})
        self.raw.update_many({"settlement_state": "queuing"}, {"$set": {"settlement_state": "pending", "recovered_after_restart": datetime.utcnow()}})
        # If WhatsApp already returned a message key, the only missing step was
        # our local /result acknowledgement. Mark it sent on restart; never
        # send the table again.
        self.outbox.update_many(
            {"state": "sending", "delivery_message": {"$exists": True}},
            {"$set": {"state": "sent", "recovered_after_restart": datetime.utcnow()}},
        )
        # A process/backend outage after WhatsApp send but before /delivery is
        # unknowable. Keeping it uncertain is intentionally safer than a blind
        # retry which could post the same table twice in an output group.
        self.outbox.update_many(
            {"state": "sending", "delivery_message": {"$exists": False}, "send_attempted_at": {"$exists": True}},
            {"$set": {"state": "uncertain", "recovered_after_restart": datetime.utcnow(), "last_error": "WhatsApp send attempted; delivery confirmation missing"}},
        )
        self.outbox.update_many(
            {"state": "sending", "send_attempted_at": {"$exists": False}},
            {"$set": {"state": "retry", "recovered_after_restart": datetime.utcnow()}},
        )

    def capture_raw(self, document: dict) -> tuple[dict, bool]:
        """Idempotent insert: duplicate Baileys upserts never make duplicate replies."""
        document["received_at"] = datetime.utcnow()
        document["business_date"] = self.date
        document["state"] = "received"
        document["normal_state"] = "pending"
        document["final_reply_state"] = "pending"
        document["settlement_state"] = "pending"
        try:
            self.raw.insert_one(document)
            return document, True
        except DuplicateKeyError:
            saved = self.raw.find_one({
                "client_name": document["client_name"], "session_name": document["session_name"],
                "source_jid": document["source_jid"], "message_id": document["message_id"],
            })
            return saved, False

    def sync_group_mappings(self, client_name: str, session_name: str, mappings: list[dict]) -> int:
        """Persist the group names resolved by the logged-in Baileys account.

        The YAML stays human-readable (names only); WhatsApp JIDs are resolved
        after each connection and retained here for backend-side auditing and
        future jobs. A rename is refreshed safely on the next reconnect.
        """
        now = datetime.utcnow()
        updated = 0
        for item in mappings:
            name = str(item.get("group_name") or "").strip()
            name_key = str(item.get("group_name_key") or "").strip().lower()
            jid = str(item.get("jid") or "").strip()
            if not name or not name_key or not jid:
                continue
            # Prefer the JID row so a WhatsApp group rename updates the same
            # durable mapping instead of trying to insert a second JID row.
            existing = self.group_mappings.find_one(
                {"client_name": client_name, "session_name": session_name, "jid": jid},
                {"_id": 1},
            )
            selector = {"_id": existing["_id"]} if existing else {
                "client_name": client_name, "session_name": session_name, "group_name_key": name_key,
            }
            self.group_mappings.update_one(
                selector,
                {"$set": {
                    "client_name": client_name,
                    "session_name": session_name,
                    "group_name": name,
                    "group_name_key": name_key,
                    "jid": jid,
                    "roles": sorted({str(role) for role in (item.get("roles") or []) if role}),
                    "resolved_at": now,
                }},
                upsert=True,
            )
            updated += 1
        return updated

    def group_name_for_jid(self, client_name: str, session_name: str, jid: str) -> str | None:
        row = self.group_mappings.find_one(
            {"client_name": client_name, "session_name": session_name, "jid": jid},
            {"group_name": 1},
        )
        return str(row["group_name"]) if row and row.get("group_name") else None

    def group_jid_for_name(self, client_name: str, session_name: str, group_name: str) -> str | None:
        target = " ".join(str(group_name or "").casefold().split())
        if not target:
            return None
        for row in self.group_mappings.find(
            {"client_name": client_name, "session_name": session_name},
            {"group_name": 1, "group_name_key": 1, "jid": 1},
        ):
            name = " ".join(str(row.get("group_name") or "").casefold().split())
            key = " ".join(str(row.get("group_name_key") or "").casefold().split())
            if target in {name, key} and row.get("jid"):
                return str(row["jid"])
        return None

    def available_output_groups(self, client_name: str, session_name: str) -> list[str]:
        """Connected-account group names safe to offer as output destinations."""
        rows = self.group_mappings.find(
            {"client_name": client_name, "session_name": session_name},
            {"group_name": 1, "roles": 1},
        )
        names = {
            str(row.get("group_name")).strip()
            for row in rows
            if row.get("group_name") and "input" not in (row.get("roles") or [])
        }
        return sorted(names, key=str.casefold)

    def resolved_group_mappings(self, client_name: str, session_name: str) -> list[dict]:
        """Small safe view for the desktop: real WhatsApp name/JID and route role."""
        rows = self.group_mappings.find(
            {"client_name": client_name, "session_name": session_name},
            {"_id": 0, "group_name": 1, "jid": 1, "roles": 1, "resolved_at": 1},
        )
        return sorted(
            ({
                "name": str(row.get("group_name") or ""),
                "jid": str(row.get("jid") or ""),
                "roles": sorted(str(role) for role in (row.get("roles") or [])),
                "resolved_at": row.get("resolved_at").isoformat() if row.get("resolved_at") else "",
            } for row in rows),
            key=lambda row: row["name"].casefold(),
        )

    def cancel_target(self, client_name: str, session_name: str, source_jid: str, quoted_message_id: str) -> dict | None:
        """Find the original input behind a WhatsApp quoted cancel command.

        A user may reply either to their own play or to the bot's immediate
        acknowledgement. Both must point to the same raw play record.
        """
        if not quoted_message_id:
            return None
        raw = self.raw.find_one({
            "client_name": client_name,
            "session_name": session_name,
            "source_jid": source_jid,
            "message_id": quoted_message_id,
        })
        if raw:
            return raw
        sent = self.outbox.find_one({
            "client_name": client_name,
            "session_name": session_name,
            "delivery_jid": source_jid,
            "delivery_message.key.id": quoted_message_id,
            "raw_id": {"$exists": True, "$ne": None},
        })
        return self.raw.find_one({"_id": sent["raw_id"]}) if sent and sent.get("raw_id") else None

    def mark_invalid_raw_cancelled(self, raw_id, cancel_message_id: str) -> bool:
        """Close one invalid play exactly once; never create a cancel debit."""
        result = self.raw.update_one(
            {"_id": raw_id, "invalid_cancel_state": {"$ne": "cancelled"}},
            {"$set": {
                "invalid_cancel_state": "cancelled",
                "invalid_cancelled_at": datetime.utcnow(),
                "invalid_cancel_message_id": cancel_message_id,
            }},
        )
        return result.modified_count == 1

    def delete_invalid_legacy_record(self, raw_id) -> int:
        """Remove the diagnostic DB row created for an invalid format.

        Valid plays always have `Total`; this deliberately deletes only the
        old '*Pls Check MSG*' style record with the same original Message_ID.
        The durable raw audit row is retained and marked cancelled separately.
        """
        raw = self.raw.find_one({"_id": raw_id})
        if not raw:
            return 0
        result = self.db[raw["business_date"]].delete_many({
            "Message_ID": raw["message_id"],
            "Total": {"$exists": False},
        })
        return result.deleted_count

    def claim_next_pending(self, client_name: str, session_name: str, source_jid: str | None = None) -> dict | None:
        query = {"client_name": client_name, "session_name": session_name, "state": "received"}
        if source_jid:
            query["source_jid"] = source_jid
        return self.raw.find_one_and_update(
            query,
            {"$set": {"state": "processing", "processing_at": datetime.utcnow()}},
            # WhatsApp timestamp retains start-to-end order even when an offline
            # append event delivers many messages in the same millisecond.
            sort=[("message_timestamp", ASCENDING), ("received_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    def mark_raw(self, raw_id, state: str, **extra) -> None:
        self.raw.update_one({"_id": raw_id}, {"$set": {"state": state, **extra}})

    def claim_next_final_reply(self, client_name: str, session_name: str, source_jid: str | None = None) -> dict | None:
        """Reserve one already-processed message for the end-of-day quoted reply."""
        query = {
            "client_name": client_name,
            "session_name": session_name,
            "state": {"$in": ["processed", "replied", "reply_pending"]},
            "final_reply_state": "pending",
            "legacy_reply": {"$nin": [None, ""]},
        }
        if source_jid:
            query["source_jid"] = source_jid
        return self.raw.find_one_and_update(
            query,
            {"$set": {"final_reply_state": "queuing", "final_reply_queuing_at": datetime.utcnow()}},
            sort=[("message_timestamp", ASCENDING), ("received_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    def mark_final_reply_queued(self, raw_id) -> None:
        self.raw.update_one({"_id": raw_id}, {"$set": {"final_reply_state": "queued", "final_reply_queued_at": datetime.utcnow()}})

    def pending_settlements(self, client_name: str, session_name: str, source_jid: str | None = None, limit: int = 1000) -> list[dict]:
        query = {
            "client_name": client_name,
            "session_name": session_name,
            "state": "processed",
            "settlement_state": {"$in": [None, "pending"]},
        }
        if source_jid:
            query["source_jid"] = source_jid
        return list(self.raw.find(query).sort([("message_timestamp", ASCENDING), ("received_at", ASCENDING)]).limit(limit))

    def pending_input_group_settlements(self, client_name: str, session_name: str, limit: int = 10000, business_date: str | None = None) -> list[dict]:
        """Input plays still waiting for their one end-of-day group total.

        `source_jid` is the actual configured input group. Keeping this on the
        durable raw row prevents one input group's play from being mixed with
        another group, including after restart or the midnight rollover.
        """
        query = {
            "client_name": client_name,
            "session_name": session_name,
            "state": "processed",
            "settlement_state": {"$in": [None, "pending"]},
        }
        if business_date:
            query["business_date"] = business_date
        return list(self.raw.find(query).sort([
            ("source_jid", ASCENDING),
            ("business_date", ASCENDING),
            ("message_timestamp", ASCENDING),
            ("received_at", ASCENDING),
        ]).limit(limit))

    def reserve_settlement(self, raw_id) -> bool:
        result = self.raw.update_one(
            {"_id": raw_id, "settlement_state": {"$in": [None, "pending"]}},
            {"$set": {"settlement_state": "queuing", "settlement_queuing_at": datetime.utcnow()}},
        )
        return result.modified_count == 1

    def release_settlement(self, raw_id) -> None:
        self.raw.update_one({"_id": raw_id}, {"$set": {"settlement_state": "pending"}})

    def skip_settlement(self, raw_id, reason: str) -> None:
        self.raw.update_one({"_id": raw_id}, {"$set": {"settlement_state": "skipped", "settlement_skip_reason": reason}})

    def mark_settlement_queued(self, raw_id, details: dict) -> None:
        self.raw.update_one({"_id": raw_id}, {"$set": {"settlement_state": "queued", "settlement_details": details, "settlement_queued_at": datetime.utcnow()}})

    def result_document(self, business_date: str) -> dict:
        return self.db[business_date].find_one({"Result": True}) or {}

    def legacy_transaction(self, raw: dict) -> dict | None:
        return self.db[raw["business_date"]].find_one({"Message_ID": raw["message_id"], "Total": {"$exists": True}})

    def mark_legacy_transaction_settled(self, raw_id) -> None:
        raw = self.raw.find_one({"_id": raw_id})
        if raw:
            self.db[raw["business_date"]].update_one(
                {"Message_ID": raw["message_id"], "Total": {"$exists": True}},
                {"$set": {"Settled": True, "SettlementReplyAt": datetime.utcnow()}},
            )

    def add_transaction(self, document: dict) -> None:
        self.transactions.insert_one(document)

    def enqueue(self, message: dict) -> None:
        message.update({
            "state": "pending", "attempts": 0, "created_at": datetime.utcnow(),
            "next_attempt_at": datetime.utcnow(), "business_date": message.get("business_date") or self.date,
            # Lower number is not special; claim_outbox sorts this descending.
            "priority": int(message.get("priority", 50)),
            "send_attempt_id": message.get("send_attempt_id") or uuid.uuid4().hex,
        })
        try:
            self.outbox.insert_one(message)
        except DuplicateKeyError:
            # The final reply was already queued by an earlier "last" trigger.
            pass

    def mark_outbox_delivery(self, message_id: str, target_jid: str, sent_message: dict) -> None:
        from bson import ObjectId
        self.outbox.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"delivery_jid": target_jid, "delivery_message": sent_message, "delivered_at": datetime.utcnow()}},
        )

    def mark_outbox_send_attempt(self, message_id: str) -> bool:
        """Persist intent *before* calling WhatsApp.

        A bridge that cannot create this record must not call sendMessage. This
        is what makes a failed /delivery callback non-duplicating.
        """
        from bson import ObjectId
        result = self.outbox.update_one(
            {"_id": ObjectId(message_id), "state": "sending"},
            {"$set": {"send_attempted_at": datetime.utcnow()}},
        )
        return result.modified_count == 1

    def mark_outbox_uncertain(self, message_id: str, error: str) -> None:
        """Stop automatic retries after WhatsApp accepted a send but local
        confirmation was unavailable. Operator can verify the group and use
        /resolve with sent=true or sent=false."""
        from bson import ObjectId
        self.outbox.update_one(
            {"_id": ObjectId(message_id), "state": "sending"},
            {"$set": {"state": "uncertain", "last_error": error, "updated_at": datetime.utcnow()}},
        )

    def resolve_outbox_uncertain(self, message_id: str, sent: bool) -> None:
        from bson import ObjectId
        state = "sent" if sent else "retry"
        payload = {"state": state, "resolved_at": datetime.utcnow(), "last_error": "" if sent else "Manual retry after verified unsent"}
        if not sent:
            payload["next_attempt_at"] = datetime.utcnow()
            payload["send_attempted_at"] = None
        self.outbox.update_one({"_id": ObjectId(message_id), "state": "uncertain"}, {"$set": payload})

    def pending_output_settlements(self, client_name: str, session_name: str, output_jid: str, limit: int = 1000, business_date: str | None = None) -> list[dict]:
        query = {
            "client_name": client_name,
            "session_name": session_name,
            "kind": "legacy_output",
            "state": "sent",
            "delivery_jid": output_jid,
            "market": {"$nin": [None, ""]},
            "settlement_payload": {"$ne": None},
            "delivery_message": {"$exists": True},
            "settlement_state": {"$in": [None, "pending"]},
        }
        if business_date:
            query["business_date"] = business_date
        return list(self.outbox.find(query).sort("created_at", ASCENDING).limit(limit))

    def output_settlement_details(self, client_name: str, session_name: str, output_jid: str, business_date: str) -> list[dict]:
        """All tables that already have a generated quoted settlement reply."""
        query = {
            "client_name": client_name,
            "session_name": session_name,
            "kind": "legacy_output",
            "state": "sent",
            "delivery_jid": output_jid,
            "business_date": business_date,
            "settlement_state": {"$in": ["queued", "sent"]},
            "settlement_details": {"$exists": True},
        }
        return list(self.outbox.find(query).sort("created_at", ASCENDING))

    def reserve_output_settlement(self, outbox_id) -> bool:
        result = self.outbox.update_one(
            {"_id": outbox_id, "settlement_state": {"$in": [None, "pending"]}},
            {"$set": {"settlement_state": "queuing", "settlement_queuing_at": datetime.utcnow()}},
        )
        return result.modified_count == 1

    def release_output_settlement(self, outbox_id) -> None:
        self.outbox.update_one({"_id": outbox_id}, {"$set": {"settlement_state": "pending"}})

    def mark_output_settlement_queued(self, outbox_id, details: dict) -> None:
        self.outbox.update_one(
            {"_id": outbox_id},
            {"$set": {"settlement_state": "queued", "settlement_details": details, "settlement_queued_at": datetime.utcnow()}},
        )

    def claim_outbox(self, client_name: str, session_name: str, limit: int) -> list[dict]:
        claimed = []
        for _ in range(limit):
            item = self.outbox.find_one_and_update(
                {"client_name": client_name, "session_name": session_name, "state": {"$in": ["pending", "retry"]}, "next_attempt_at": {"$lte": datetime.utcnow()}},
                {"$set": {"state": "sending", "claimed_at": datetime.utcnow()}, "$inc": {"attempts": 1}},
                sort=[("priority", -1), ("created_at", ASCENDING)], return_document=ReturnDocument.AFTER,
            )
            if not item:
                break
            item["_id"] = str(item["_id"])
            # Node only needs the outbox id. raw_id is retained in MongoDB for
            # delivery bookkeeping, but must never leak as a BSON ObjectId in
            # the JSON response to Baileys.
            if item.get("raw_id") is not None:
                item["raw_id"] = str(item["raw_id"])
            claimed.append(item)
        return claimed

    def outbox_result(self, message_id: str, sent: bool, error: str = "") -> None:
        from bson import ObjectId
        item = self.outbox.find_one({"_id": ObjectId(message_id)})
        state = "sent" if sent else "retry"
        payload = {"state": state, "last_error": error, "updated_at": datetime.utcnow()}
        if not sent:
            # Exponential backoff avoids a disconnected WhatsApp session causing
            # a tight retry loop. Cap is five minutes.
            attempts = int((item or {}).get("attempts", 1))
            payload["next_attempt_at"] = datetime.utcnow() + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
            # sendMessage itself failed, so retry is safe. The previous attempt
            # marker must not turn this known failure into an uncertain send.
            payload["send_attempted_at"] = None
        self.outbox.update_one({"_id": ObjectId(message_id)}, {"$set": payload})
        if sent and item:
            if item.get("kind") == "normal_source_reply" and item.get("raw_id"):
                self.raw.update_one({"_id": item["raw_id"]}, {"$set": {"normal_reply_state": "sent", "normal_replied_at": datetime.utcnow()}})
            elif item.get("kind") in {"final_source_reply", "source_reply"} and item.get("raw_id"):
                self.raw.update_one({"_id": item["raw_id"]}, {"$set": {"final_reply_state": "sent", "final_replied_at": datetime.utcnow()}})
            elif item.get("kind") == "settlement_source_reply" and item.get("raw_id"):
                self.raw.update_one({"_id": item["raw_id"]}, {"$set": {"settlement_state": "sent", "settlement_sent_at": datetime.utcnow()}})
                self.mark_legacy_transaction_settled(item["raw_id"])
            elif item.get("kind") == "settlement_output_reply" and item.get("reply_to_outbox_id"):
                self.outbox.update_one(
                    {"_id": item["reply_to_outbox_id"]},
                    {"$set": {"settlement_state": "sent", "settlement_sent_at": datetime.utcnow()}},
                )
            elif item.get("kind") == "settlement_input_group_total":
                raw_ids = item.get("source_raw_ids") or []
                if raw_ids:
                    self.raw.update_many(
                        {"_id": {"$in": raw_ids}},
                        {"$set": {"settlement_state": "sent", "settlement_sent_at": datetime.utcnow()}},
                    )
                    for raw_id in raw_ids:
                        self.mark_legacy_transaction_settled(raw_id)

    def mark_outbox_invalid_target(self, message_id: str, error: str) -> None:
        """A config target missing from WhatsApp cannot succeed on retry."""
        from bson import ObjectId
        self.outbox.update_one(
            {"_id": ObjectId(message_id), "state": "sending"},
            {"$set": {"state": "failed", "last_error": error, "updated_at": datetime.utcnow(), "failed_reason": "unknown_output_group"}},
        )


db = Database()
