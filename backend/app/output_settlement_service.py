from __future__ import annotations

from .database import db
from .settings import find_session
from .settlement_service import settlement_service


DEFAULT_ICONS = {"ank": "🔵", "sp": "🟢", "dp": "🟠", "tp": "🔴", "jodi": "🟣"}


def _amount(value) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _panna_type(value: str) -> str:
    unique = len(set(value))
    return "tp" if unique == 1 else "dp" if unique == 2 else "sp"


class OutputSettlementService:
    """Settles the actual table message sent to an output group.

    Each output outbox item keeps its original Baileys key, so the final reply
    appears directly above the table message rather than above an input play.
    """

    @staticmethod
    def _market_parts(market: str) -> tuple[str, str] | tuple[None, None]:
        if market.endswith("_OP"):
            return market[:-3], "OP"
        if market.endswith("_CL"):
            return market[:-3], "CL"
        return None, None

    @staticmethod
    def _values(result_doc: dict, base_market: str, side: str) -> dict | None:
        value = result_doc.get(base_market) or {}
        required = ("OPEN", "OPANAL", "CLOSE", "CPANAL")
        if not all(str(value.get(key, "")).strip() for key in required):
            return None
        open_ank, close_ank = str(value["OPEN"]), str(value["CLOSE"])
        return {
            "ank": open_ank if side == "OP" else close_ank,
            "panna": str(value["OPANAL"] if side == "OP" else value["CPANAL"]),
            "jodi": f"{open_ank}{close_ank}",
            "display": f"{value['OPANAL']}-{open_ank}{close_ank}-{value['CPANAL']}",
        }

    @staticmethod
    def _matches(bets: dict, values: dict) -> dict[str, list[tuple[str, int]]]:
        matches = {key: [] for key in ("ank", "sp", "dp", "tp", "jodi")}
        for number, amount in (bets or {}).items():
            token, stake = str(number).strip(), _amount(amount)
            if stake <= 0:
                continue
            if len(token) == 1 and token == values["ank"]:
                matches["ank"].append((token, stake))
            elif len(token) == 2 and token == values["jodi"]:
                matches["jodi"].append((token, stake))
            elif len(token) == 3 and token == values["panna"]:
                matches[_panna_type(token)].append((token, stake))
        return matches

    @staticmethod
    def _reply(market: str, values: dict, matches: dict[str, list[tuple[str, int]]], total_play: int, icons: dict) -> tuple[str, dict]:
        title = f"*{market}*\n*RESULT: {values['display']}*"
        if not any(matches.values()):
            return f"{title}\n*NO WIN*", {
                "result": values["display"], "matches": {},
                "totals": {key: 0 for key in ("ank", "sp", "dp", "tp", "jodi")},
                "total_play": total_play,
            }

        labels = {"ank": "Ank", "sp": "SP", "dp": "DP", "tp": "TP", "jodi": "Jodi"}
        lines = [title]
        totals = {}
        for key in ("ank", "sp", "dp", "tp", "jodi"):
            total = sum(amount for _number, amount in matches[key])
            totals[key] = total
            for number, amount in matches[key]:
                lines.append(f"{icons[key]} *{labels[key]}* {number} = {amount}")
        # A quoted reply is intentionally short: it identifies only this
        # table's winning numbers. All category/play totals belong to exactly
        # one final group message, after every quoted reply has been sent.
        return "\n".join(lines), {"result": values["display"], "matches": matches, "totals": totals, "total_play": total_play}

    @staticmethod
    def _group_total(items: list[dict], icons: dict) -> str:
        totals = {key: 0 for key in ("ank", "sp", "dp", "tp", "jodi")}
        total_play = 0
        for item in items:
            for key, amount in (item.get("totals") or {}).items():
                totals[key] = totals.get(key, 0) + _amount(amount)
            total_play += _amount(item.get("total_play"))
        dates = sorted({str(item.get("business_date", "")) for item in items if item.get("business_date")})
        # MongoDB collection date is YY-MM-DD; show customers DD-MM-YY.
        date = dates[0] if dates else ""
        if len(date.split("-")) == 3:
            year, month, day = date.split("-")
            date = f"{day}-{month}-{year}"
        return "\n".join([
            f"*DATE: {date}*" if date else "*FINAL GROUP TOTAL*",
            f"{icons['ank']} *TOTAL ANK = {totals['ank']}*",
            f"{icons['sp']} *TOTAL SP = {totals['sp']}*",
            f"{icons['jodi']} *TOTAL JODI = {totals['jodi']}*",
            f"{icons['dp']} *TOTAL DP = {totals['dp']}*",
            f"{icons['tp']} *TOTAL TP = {totals['tp']}*",
            f"*TOTAL PLAY = {total_play}*",
        ])

    @staticmethod
    def _input_group_total(business_date: str, totals: dict, total_play: int, icons: dict) -> str:
        """The single final message for one input WhatsApp group."""
        year, month, day = business_date.split("-")
        return "\n".join([
            f"*DATE: {day}-{month}-{year}*",
            f"{icons['ank']} *TOTAL ANK = {totals['ank']}*",
            f"{icons['sp']} *TOTAL SP = {totals['sp']}*",
            f"{icons['jodi']} *TOTAL JODI = {totals['jodi']}*",
            f"{icons['dp']} *TOTAL DP = {totals['dp']}*",
            f"{icons['tp']} *TOTAL TP = {totals['tp']}*",
            f"*TOTAL PLAY = {total_play}*",
        ])

    def _queue_input_group_totals(self, client_name: str, session_name: str, trigger_message_id: str, icons: dict, limit: int) -> dict:
        """Queue one end-total per input group, based only on that group's plays.

        A raw play is marked queued only when its local Result exists and the
        group total has entered the durable outbox. Missing results stay
        pending for the next `last`; they are never counted as no-win.
        """
        rates = settlement_service._rates(client_name, session_name)
        result_cache: dict[str, dict] = {}
        groups: dict[tuple[str, str], dict] = {}
        counts = {"input_group_totals_queued": 0, "input_waiting_result": 0, "input_skipped": 0}

        for raw in db.pending_input_group_settlements(client_name, session_name, limit):
            transaction = db.legacy_transaction(raw)
            if not transaction:
                db.skip_settlement(raw["_id"], "legacy_transaction_not_found")
                counts["input_skipped"] += 1
                continue
            base_market, side = self._market_parts(str(transaction.get("Market", "")))
            if not base_market:
                db.skip_settlement(raw["_id"], "unsupported_market")
                counts["input_skipped"] += 1
                continue
            business_date = str(raw["business_date"])
            result_doc = result_cache.setdefault(business_date, db.result_document(business_date))
            values = settlement_service._result_values(base_market, side, result_doc)
            if not values:
                counts["input_waiting_result"] += 1
                continue

            key = (str(raw["source_jid"]), business_date)
            group = groups.setdefault(key, {
                "raws": [],
                "totals": {name: 0 for name in ("ank", "sp", "dp", "tp", "jodi")},
                "total_play": 0,
            })
            group["raws"].append(raw)
            group["total_play"] += _amount(transaction.get("Total"))
            for win in settlement_service._winning_rows(transaction, values, rates):
                category = win["kind"].replace("single_panna", "sp").replace("double_panna", "dp").replace("triple_panna", "tp")
                group["totals"][category] += _amount(win["win"])

        for (source_jid, business_date), group in groups.items():
            reserved = []
            for raw in group["raws"]:
                if db.reserve_settlement(raw["_id"]):
                    reserved.append(raw)
            # A repeated concurrent trigger must not produce a partial total.
            if len(reserved) != len(group["raws"]):
                for raw in reserved:
                    db.release_settlement(raw["_id"])
                continue
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": source_jid,
                "text": self._input_group_total(business_date, group["totals"], group["total_play"], icons),
                "quote": None,
                "kind": "settlement_input_group_total",
                "source_raw_ids": [raw["_id"] for raw in reserved],
                "dedupe_key": f"input-settlement-total:{source_jid}:{business_date}:{trigger_message_id}",
                # Output per-table replies (80) and its final summary (70)
                # leave before this input-group total (60).
                "priority": 60,
                "business_date": business_date,
            })
            for raw in reserved:
                db.mark_settlement_queued(raw["_id"], {
                    "kind": "input_group_total",
                    "business_date": business_date,
                    "source_jid": source_jid,
                    "totals": group["totals"],
                    "total_play": group["total_play"],
                })
            counts["input_group_totals_queued"] += 1
        return counts

    def queue_group(self, client_name: str, session_name: str, output_jid: str, trigger_message_id: str, limit: int = 1000) -> dict:
        processing = find_session(client_name, session_name)["session"].get("processing", {})
        icons = {**DEFAULT_ICONS, **(processing.get("settlement_icons", {}) or {})}
        result_cache: dict[str, dict] = {}
        counts = {"queued": 0, "waiting_result": 0, "group_total_queued": False}
        queued_details: list[dict] = []
        for item in db.pending_output_settlements(client_name, session_name, output_jid, limit):
            if not db.reserve_output_settlement(item["_id"]):
                continue
            base_market, side = self._market_parts(str(item["market"]))
            if item["business_date"] not in result_cache:
                result_cache[item["business_date"]] = db.result_document(item["business_date"])
            result_doc = result_cache[item["business_date"]]
            values = self._values(result_doc, base_market, side) if base_market else None
            if not values:
                db.release_output_settlement(item["_id"])
                counts["waiting_result"] += 1
                continue
            payload = item.get("settlement_payload") or {}
            total_play = _amount(payload.get("total_play"))
            matches = self._matches(payload.get("bets") or {}, values)
            reply, details = self._reply(str(item["market"]), values, matches, total_play, icons)
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": output_jid,
                "text": reply,
                "quote": item["delivery_message"],
                "kind": "settlement_output_reply",
                "reply_to_outbox_id": item["_id"],
                "dedupe_key": f"output-settlement:{item['_id']}",
                "priority": 80,
                "business_date": item["business_date"],
            })
            details["business_date"] = item["business_date"]
            db.mark_output_settlement_queued(item["_id"], details)
            counts["queued"] += 1
            queued_details.append(details)
        # The summary is sent only after every individual quoted reply has been
        # queued, and only when every table had its complete Result document.
        # The trigger WhatsApp id makes a repeated upsert of the same `last`
        # idempotent.
        if queued_details and not counts["waiting_result"]:
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": output_jid,
                "text": self._group_total(queued_details, icons),
                "quote": None,
                "kind": "settlement_group_total",
                "dedupe_key": f"output-settlement-total:{output_jid}:{trigger_message_id}",
                "priority": 70,
                "business_date": next(iter(result_cache), None),
            })
            counts["group_total_queued"] = True
        # This runs after the output queue is written. Lower priority guarantees
        # output replies and output final total go first, then one total per
        # input group calculated from only that group's MongoDB play records.
        if not counts["waiting_result"]:
            counts.update(self._queue_input_group_totals(client_name, session_name, trigger_message_id, icons, limit * 10))
        else:
            counts.update({"input_group_totals_queued": 0, "input_waiting_result": 0, "input_skipped": 0})
        return counts


output_settlement_service = OutputSettlementService()
