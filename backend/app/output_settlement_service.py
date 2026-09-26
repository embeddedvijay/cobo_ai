from __future__ import annotations

import re
from datetime import datetime

from .database import db
from .settings import find_session
from .settlement_service import settlement_service
from session_bot.debug_log import trace


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
    def _sent_text(message: dict | None) -> str:
        """Get exact text accepted by Baileys for a previously delivered table."""
        value = (message or {}).get("message", message or {})
        return str(
            value.get("conversation")
            or (value.get("extendedTextMessage") or {}).get("text")
            or (value.get("imageMessage") or {}).get("caption")
            or ""
        )

    @classmethod
    def _delivered_table_bets(cls, message: dict | None) -> dict[str, int]:
        """Parse actual WhatsApp table text as the settlement source of truth.

        Older rows may have a pre-conversion settlement_payload. The delivered
        text is the only representation the operator saw, so it wins whenever
        it contains number=amount rows.
        """
        bets: dict[str, int] = {}
        for line in cls._sent_text(message).splitlines():
            clean = line.strip().replace("*", "")
            match = re.fullmatch(r"(\d{1,3}(?:\s*-\s*\d{1,3})*)\s*=\s*(\d+)\s*₹?", clean)
            if match:
                numbers, amount = match.groups()
                # `1-8=1000₹` means both 1 and 8 have 1000.  This is also
                # how FM-expanded rows are stored and how LD/overflow total.
                for number in re.split(r"\s*-\s*", numbers):
                    bets[number] = bets.get(number, 0) + _amount(amount)
        return bets

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
    def _played_stakes(transaction: dict) -> list[tuple[str, int]]:
        """Classify every accepted input row by its played category, not win.

        A valid CANCEL stores the same rows with negative stakes. Keeping those
        negative values here makes ANK/JODI/SP/DP/TP agree with TOTAL PLAY.
        """
        played = []
        for row in transaction.get("Result", []) or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            stake = _amount(row[-1])
            if stake == 0:
                continue
            numbers = [str(value).strip() for value in row[:-1] if str(value).strip().isdigit()]
            if not numbers:
                continue
            # A grouped input row carries its stated stake on *every* number:
            # `1-8=1000` is ANK 1000 + ANK 1000, and an FM row applies to
            # each of its eight pannas.  Category totals in the input Final
            # must therefore use the same atomic rule as Forward/Overflow.
            for number in numbers:
                if len(number) == 1:
                    kind = "ank"
                elif len(number) == 2:
                    kind = "jodi"
                elif len(number) == 3:
                    kind = _panna_type(number)
                else:
                    continue
                played.append((kind, stake))
        return played

    def _matched_played_stakes(self, transaction: dict, business_date: str, result_cache: dict[str, dict]) -> list[tuple[str, int]]:
        """Return only category stakes whose exact game number won.

        Input-group Final must use the same result rule as Forward's final
        table.  Merely playing TP 111/222 must not appear in TOTAL TP unless
        that exact pannā was the result.
        """
        base_market, side = self._market_parts(str(transaction.get("Market", "")))
        if not base_market:
            return []
        result_doc = result_cache.setdefault(str(business_date), db.result_document(str(business_date)))
        values = self._values(result_doc, base_market, side)
        if not values:
            return []
        matched = []
        for row in transaction.get("Result", []) or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            stake = _amount(row[-1])
            if not stake:
                continue
            for number in (str(value).strip() for value in row[:-1] if str(value).strip().isdigit()):
                if len(number) == 1 and number == values["ank"]:
                    matched.append(("ank", stake))
                elif len(number) == 2 and number == values["jodi"]:
                    matched.append(("jodi", stake))
                elif len(number) == 3 and number == values["panna"]:
                    matched.append((_panna_type(number), stake))
        return matched

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
    def _category_total_lines(totals: dict, icons: dict) -> list[str]:
        """Only show categories that actually have a non-zero played/won amount."""
        labels = (("ank", "TOTAL ANK"), ("sp", "TOTAL SP"), ("jodi", "TOTAL JODI"), ("dp", "TOTAL DP"), ("tp", "TOTAL TP"))
        return [f"{icons[key]} *{label} = {_amount(totals.get(key))}*" for key, label in labels if _amount(totals.get(key)) != 0]

    @staticmethod
    def _group_total(items: list[dict], icons: dict) -> str:
        totals = {key: 0 for key in ("ank", "sp", "dp", "tp", "jodi")}
        total_play = 0
        for item in items:
            for key, amount in (item.get("totals") or {}).items():
                totals[key] = totals.get(key, 0) + _amount(amount)
            total_play += _amount(item.get("total_play"))
        dates = sorted({str(item.get("business_date", "")) for item in items if item.get("business_date")})
        date = dates[0] if dates else ""
        if len(date.split("-")) == 3:
            year, month, day = date.split("-")
            date = f"{day}-{month}-{year}"
        return "\n".join([
            f"*DATE: {date}*" if date else "*FINAL GROUP TOTAL*",
            *OutputSettlementService._category_total_lines(totals, icons),
            f"*TOTAL PLAY = {total_play}*",
        ])

    @staticmethod
    def _input_group_total(business_date: str, totals: dict, total_play: int, icons: dict) -> str:
        """The single final message for one input WhatsApp group."""
        year, month, day = business_date.split("-")
        return "\n".join([
            f"*DATE: {day}-{month}-{year}*",
            *OutputSettlementService._category_total_lines(totals, icons),
            f"*TOTAL PLAY = {total_play}*",
        ])

    @staticmethod
    def _input_group_message_play(business_date: str, message_totals: list[int], total_play: int) -> str:
        """A clean auditable expression: only each accepted message's play."""
        year, month, day = business_date.split("-")
        expression = " + ".join(str(_amount(total)) for total in message_totals if _amount(total) != 0) or "0"
        return "\n".join([
            f"*DATE: {day}-{month}-{year}*",
            "*MESSAGE-WISE PLAY*",
            f"{expression} = *{total_play}*",
        ])

    @staticmethod
    def _customer_rule(client_name: str, session_name: str, source_jid: str) -> tuple[str, dict]:
        """Find the saved input-group rule even though the ledger uses the JID."""
        session = find_session(client_name, session_name)["session"]
        # Electron persists the complete rule object in contact_rules.  The
        # in_contacts field is only the old `Name ^ LD` list, not a mapping.
        contacts = session.get("contact_rules", {}) or {}
        display_name = db.group_name_for_jid(client_name, session_name, source_jid) or source_jid
        for name, rule in (contacts.items() if isinstance(contacts, dict) else []):
            if str(name) in {source_jid, display_name}:
                return str(name), rule if isinstance(rule, dict) else {}
        return display_name, {}

    @staticmethod
    def _customer_rates(rule: dict, client_name: str, session_name: str) -> dict:
        fallback = settlement_service._rates(client_name, session_name)
        configured = rule.get("win_rate", {}) if isinstance(rule, dict) else {}
        aliases = {
            "ank": "ANK", "jodi": "Jodi", "single_panna": "SP",
            "double_panna": "DP", "triple_panna": "TP",
        }
        rates = dict(fallback)
        for key, label in aliases.items():
            value = configured.get(label, configured.get(key))
            if value not in (None, ""):
                try:
                    rates[key] = float(value)
                except (TypeError, ValueError):
                    pass
        return rates

    def _hisab_total_win(self, raws: list[dict], client_name: str, session_name: str, rule: dict) -> int:
        """Calculate a signed payout from the same accepted/cancelled rows in Final.

        Negative cancel rows reduce both play and winning liability, so Hisab
        remains correct after a normal cancel or desktop reject revision.
        """
        rates = self._customer_rates(rule, client_name, session_name)
        result_cache: dict[str, dict] = {}
        total = 0.0
        for raw in raws:
            transaction = db.legacy_transaction(raw)
            if not transaction or transaction.get("Deleted") is True:
                continue
            base_market, side = settlement_service._market_parts(str(transaction.get("Market", "")))
            if not base_market:
                continue
            result_doc = result_cache.setdefault(str(raw["business_date"]), db.result_document(str(raw["business_date"])))
            values = settlement_service._result_values(base_market, side, result_doc)
            if not values:
                continue
            for row in transaction.get("Result", []) or []:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                stake = _amount(row[-1])
                if not stake:
                    continue
                candidates = [str(value).strip() for value in row[:-1] if str(value).strip().isdigit()]
                choices = []
                for token in candidates:
                    if len(token) == 1 and token == values["ank"]:
                        choices.append(("ank", token))
                    elif len(token) == 2 and token == values["jodi"]:
                        choices.append(("jodi", token))
                    elif len(token) == 3 and token == values["panna"]:
                        choices.append(({"sp": "single_panna", "dp": "double_panna", "tp": "triple_panna"}[_panna_type(token)], token))
                if choices:
                    kind, _token = max(choices, key=lambda item: rates[item[0]])
                    total += stake * rates[kind]
        return int(total)

    def _save_hisab(self, client_name: str, session_name: str, source_jid: str, business_date: str, group: dict, final_message: str, message_play: str) -> None:
        customer_name, rule = self._customer_rule(client_name, session_name, source_jid)
        commission_rate = _amount((rule.get("win_rate", {}) or {}).get("Commission", 0))
        total_play = _amount(group["total_play"])
        total_win = self._hisab_total_win(group["raws"], client_name, session_name, rule)
        commission_amount = int(total_play * commission_rate / 100)
        # Positive is operator profit/customer debit; negative is operator loss.
        profit_loss = total_play - total_win - commission_amount
        db.save_hisab_snapshot({
            "client_name": client_name, "session_name": session_name,
            "source_jid": source_jid, "customer_name": customer_name,
            "business_date": business_date, "category_totals": dict(group["totals"]),
            "message_totals": list(group["message_totals"]), "total_play": total_play,
            "total_win": total_win, "commission_rate": commission_rate,
            "commission_amount": commission_amount, "profit_loss": profit_loss,
            "final_message": final_message, "message_play": message_play,
        })

    def _queue_input_group_totals(self, client_name: str, session_name: str, trigger_message_id: str, icons: dict, limit: int, business_date: str, output_jid: str) -> dict:
        """Queue one end-total per input group, based only on that group's plays.

        This is a play/stake statement, so it deliberately does not depend on
        a market result or any payout calculation.
        """
        groups: dict[tuple[str, str], dict] = {}
        counts = {"input_group_totals_queued": 0, "input_waiting_result": 0, "input_skipped": 0}
        result_cache: dict[str, dict] = {}

        for raw in db.pending_input_group_settlements(client_name, session_name, limit, business_date=business_date):
            transaction = db.legacy_transaction(raw)
            if not transaction:
                db.skip_settlement(raw["_id"], "legacy_transaction_not_found")
                counts["input_skipped"] += 1
                continue
            base_market, _side = self._market_parts(str(transaction.get("Market", "")))
            if not base_market:
                db.skip_settlement(raw["_id"], "unsupported_market")
                counts["input_skipped"] += 1
                continue
            business_date = str(raw["business_date"])
            key = (str(raw["source_jid"]), business_date)
            group = groups.setdefault(key, {
                "raws": [],
                "totals": {name: 0 for name in ("ank", "sp", "dp", "tp", "jodi")},
                "message_totals": [],
                "total_play": 0,
            })
            group["raws"].append(raw)
            message_total = _amount(transaction.get("Total"))
            group["message_totals"].append(message_total)
            group["total_play"] += message_total
            for category, stake in self._matched_played_stakes(transaction, business_date, result_cache):
                group["totals"][category] += stake

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
            final_message = self._input_group_total(business_date, group["totals"], group["total_play"], icons)
            message_play = self._input_group_message_play(business_date, group["message_totals"], group["total_play"])
            self._save_hisab(client_name, session_name, source_jid, business_date, group, final_message, message_play)
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": source_jid,
                "text": final_message,
                "quote": None,
                "kind": "settlement_input_group_total",
                "source_raw_ids": [raw["_id"] for raw in reserved],
                "dedupe_key": f"input-settlement-total:{source_jid}:{business_date}:{trigger_message_id}",
                # Output per-table replies (80) and its final summary (70)
                # leave before this input-group total (60).
                "priority": 60,
                "business_date": business_date,
                "final_stage": "input_group_total",
                "depends_on": {"type": "output_group_total", "output_jid": output_jid, "business_date": business_date},
            })
            # This follows the date-wise final total in the same input group,
            # and makes every accepted message amount auditable at a glance.
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": source_jid,
                "text": message_play,
                "quote": None,
                "kind": "settlement_input_group_message_play",
                "dedupe_key": f"input-message-play:{source_jid}:{business_date}:{trigger_message_id}",
                # The group total (60) is deliberately delivered immediately
                # before this message-wise expression (59).
                "priority": 59,
                "business_date": business_date,
                "final_stage": "input_group_message_play",
                "depends_on": {"type": "input_group_total", "business_date": business_date},
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

    def queue_input_group_revision(self, client_name: str, session_name: str, source_jid: str, business_date: str, revision_id: str) -> bool:
        """Send the ordinary input-group final again after an operator reject.

        The customer sees the same date-wise total and message-wise play
        format as Run Final; revision bookkeeping remains backend-only.
        """
        processing = find_session(client_name, session_name)["session"].get("processing", {})
        icons = {**DEFAULT_ICONS, **(processing.get("settlement_icons", {}) or {})}
        totals = {name: 0 for name in ("ank", "sp", "dp", "tp", "jodi")}
        message_totals, total_play = [], 0
        result_cache: dict[str, dict] = {}
        for raw in db.input_group_rows(client_name, session_name, source_jid, business_date):
            transaction = db.legacy_transaction(raw)
            if not transaction or transaction.get("Deleted") is True:
                continue
            if not self._market_parts(str(transaction.get("Market", "")))[0]:
                continue
            message_total = _amount(transaction.get("Total"))
            message_totals.append(message_total)
            total_play += message_total
            for category, stake in self._matched_played_stakes(transaction, business_date, result_cache):
                totals[category] += stake
        key = f"input-revision:{source_jid}:{business_date}:{revision_id}"
        final_message = self._input_group_total(business_date, totals, total_play, icons)
        message_play = self._input_group_message_play(business_date, message_totals, total_play)
        self._save_hisab(client_name, session_name, source_jid, business_date, {
            "raws": db.input_group_rows(client_name, session_name, source_jid, business_date),
            "totals": totals, "message_totals": message_totals, "total_play": total_play,
        }, final_message, message_play)
        db.enqueue({
            "client_name": client_name, "session_name": session_name,
            "channel": "whatsapp", "target": source_jid,
            "text": final_message,
            "quote": None, "kind": "settlement_input_group_total",
            "dedupe_key": key + ":total", "priority": 60, "business_date": business_date,
        })
        db.enqueue({
            "client_name": client_name, "session_name": session_name,
            "channel": "whatsapp", "target": source_jid,
            "text": message_play,
            "quote": None, "kind": "settlement_input_group_message_play",
            "dedupe_key": key + ":messages", "priority": 59, "business_date": business_date,
        })
        return True

    @staticmethod
    def _market_active_on_business_date(session: dict, market: str, business_date: str) -> bool:
        """Use the saved Active Days for the trading date, not today's weekday.

        Run Final can run after midnight, so the business date is the only
        safe day to test. A malformed/legacy timing remains active rather
        than silently dropping a real table.
        """
        try:
            weekday = datetime.strptime(str(business_date), "%y-%m-%d").weekday()
        except ValueError:
            return True
        selected = (session.get("market_days") or {}).get(market)
        if isinstance(selected, (list, tuple, set)):
            try:
                return weekday in {int(day) % 7 for day in selected}
            except (TypeError, ValueError):
                return True
        row = (session.get("market_timings") or {}).get(market)
        try:
            # Legacy timing stores the final active weekday index:
            # 4 = Mon-Fri, 5 = Mon-Sat, 6 = Mon-Sun.
            return weekday <= int(row[1])
        except (TypeError, ValueError, IndexError):
            return True

    def queue_group(self, client_name: str, session_name: str, output_jid: str, trigger_message_id: str, limit: int = 1000) -> dict:
        """Queue one selected output group completely before any input final.

        A dashboard Run Final is deliberately two-phase: every eligible table
        reply for the selected output group, then its group total, then input
        group totals.  If even one table is missing its Result, phase two is
        held rather than sending customer totals in the middle of that output
        group's final run.  Nothing is lost: the pending rows remain reserved
        as pending and the operator can run the same selected group again.
        """
        session = find_session(client_name, session_name)["session"]
        processing = session.get("processing", {})
        icons = {**DEFAULT_ICONS, **(processing.get("settlement_icons", {}) or {})}
        result_cache: dict[str, dict] = {}
        counts = {"queued": 0, "waiting_result": 0, "off_day_skipped": 0, "group_total_queued": False}
        queued_details: list[dict] = []
        active_business_date = db.date
        trace(f"[RUN FINAL] start client={client_name} session={session_name} output_jid={output_jid} date={active_business_date} trigger={trigger_message_id}")
        # Recover only earlier input final messages that are explicitly
        # uncertain.  Their exact saved text/source ids are retained, so a
        # successful recovered total settles the same raw rows as the original.
        recovered_input_finals = 0
        for prior in db.uncertain_input_group_final_messages(
            client_name, session_name, active_business_date, limit * 10
        ):
            if not db.reserve_input_group_final_recovery(prior["_id"]):
                continue
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": prior["target"],
                "text": prior["text"],
                "quote": None,
                "kind": prior["kind"],
                "source_raw_ids": prior.get("source_raw_ids") or [],
                "dedupe_key": f"input-final-recovery:{prior['_id']}",
                "priority": int(prior.get("priority", 60)),
                "business_date": prior["business_date"],
                "final_stage": "input_final_recovery",
                "depends_on": (
                    {"type": "output_group_total", "output_jid": output_jid, "business_date": prior["business_date"]}
                    if prior["kind"] == "settlement_input_group_total"
                    else {"type": "input_group_total", "business_date": prior["business_date"]}
                ),
            })
            db.mark_input_group_final_recovery_queued(prior["_id"])
            recovered_input_finals += 1
            trace(f"[RUN FINAL] recovered uncertain input final outbox_id={prior['_id']} kind={prior.get('kind')} target={prior.get('target')}")
        counts["recovered_input_finals"] = recovered_input_finals

        # A historical missing result must never block today's final message.
        overflow_jids = set()
        for rule in (session.get("contact_rules", {}) or {}).values():
            target = str(((rule or {}).get("overflow_limits", {}) or {}).get("output_group") or "").strip()
            if target:
                overflow_jids.add(target if target.endswith("@g.us") else (db.group_jid_for_name(client_name, session_name, target) or target))
        is_overflow_output = output_jid in overflow_jids
        trace(f"[RUN FINAL] output kind={'overflow' if is_overflow_output else 'standard'} output_jid={output_jid}")
        for item in db.pending_output_settlements(client_name, session_name, output_jid, limit, business_date=active_business_date, include_legacy_overflow=is_overflow_output):
            if not db.reserve_output_settlement(item["_id"]):
                continue
            market = str(item["market"])
            if not self._market_active_on_business_date(session, market, str(item["business_date"])):
                db.release_output_settlement(item["_id"])
                counts["off_day_skipped"] += 1
                trace(f"[RUN FINAL] output off-day skipped outbox_id={item['_id']} market={market} date={item.get('business_date')}")
                continue
            base_market, side = self._market_parts(market)
            if item["business_date"] not in result_cache:
                result_cache[item["business_date"]] = db.result_document(item["business_date"])
            result_doc = result_cache[item["business_date"]]
            values = self._values(result_doc, base_market, side) if base_market else None
            if not values:
                db.release_output_settlement(item["_id"])
                counts["waiting_result"] += 1
                trace(f"[RUN FINAL] output waiting result outbox_id={item['_id']} market={item.get('market')} date={item.get('business_date')}")
                continue
            payload = item.get("settlement_payload") or {}
            # Prefer actual delivered text. It fixes legacy CL rows where
            # settlement_payload was captured before jodi/sangam conversion.
            delivered_bets = self._delivered_table_bets(item.get("delivery_message"))
            bets = delivered_bets or (payload.get("bets") or {})
            total_play = _amount(payload.get("total_play")) or sum(_amount(value) for value in bets.values())
            matches = self._matches(bets, values)
            reply, details = self._reply(str(item["market"]), values, matches, total_play, icons)
            # Output groups receive a quoted reply only for a real win.
            # A no-win table is still settled below, so it cannot block the
            # final total or be processed again on a later Run Final.
            details["business_date"] = item["business_date"]
            if any(matches.values()):
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
                    "final_stage": "output_win_reply",
                })
                db.mark_output_settlement_queued(item["_id"], details)
            else:
                # No WhatsApp reply is intentionally sent, so this parent is
                # final now and cannot block the group total.
                db.mark_output_settlement_no_win(item["_id"], details)
                trace(f"[RUN FINAL] no-win reply suppressed and settled outbox_id={item['_id']} market={item.get('market')}")
            counts["queued"] += 1
            queued_details.append(details)
        # Older WhatsApp rate-limit failures left some actual winning quoted
        # replies in explicit `uncertain` state.  This operator-triggered
        # recovery queues each such win once with a new dedupe key.  NO WIN
        # rows have no matches and can never enter this path.
        recovered = 0
        for item in db.uncertain_winning_output_replies(
            client_name, session_name, output_jid, active_business_date, limit
        ):
            if not db.reserve_output_win_recovery(item["_id"]):
                continue
            details = item.get("settlement_details") or {}
            matches = details.get("matches") or {}
            try:
                reply, _ = self._reply(
                    str(item["market"]),
                    {"display": str(details["result"])},
                    matches,
                    _amount(details.get("total_play")),
                    icons,
                )
                db.enqueue({
                    "client_name": client_name,
                    "session_name": session_name,
                    "channel": "whatsapp",
                    "target": output_jid,
                    "text": reply,
                    "quote": item.get("delivery_message"),
                    "kind": "settlement_output_reply",
                    "reply_to_outbox_id": item["_id"],
                    "dedupe_key": f"output-settlement-recovery:{item['_id']}",
                    "priority": 80,
                    "business_date": item["business_date"],
                })
                db.mark_output_win_recovery_queued(item["_id"])
                recovered += 1
                trace(f"[RUN FINAL] recovered uncertain winning reply outbox_id={item['_id']} market={item.get('market')}")
            except (KeyError, TypeError, ValueError) as exc:
                # Preserve the parent for a later safe Run Final rather than
                # making a malformed historical row look recovered.
                db.outbox.update_one(
                    {"_id": item["_id"]},
                    {"$set": {"win_recovery_state": "pending", "win_recovery_error": str(exc)}},
                )
                trace(f"[RUN FINAL] win recovery skipped outbox_id={item['_id']} error={exc}")
        counts["recovered_win_replies"] = recovered

        # The summary is sent only after every individual quoted reply has been
        # queued, and only when every table had its complete Result document.
        # The trigger WhatsApp id makes a repeated upsert of the same `last`
        # idempotent.
        # A retry can have no newly-pending tables because individual replies
        # were already sent by an earlier trigger. Build the final from every
        # settled table for this output group and active business date instead.
        total_details = [
            item.get("settlement_details") or {}
            for item in db.output_settlement_details(
                client_name, session_name, output_jid, active_business_date
            )
        ]
        if total_details and not counts["waiting_result"]:
            db.enqueue({
                "client_name": client_name,
                "session_name": session_name,
                "channel": "whatsapp",
                "target": output_jid,
                "text": self._group_total(total_details, icons),
                "quote": None,
                "kind": "settlement_group_total",
                # One final total per output group/business day even if
                # operator sends the trigger again for recovery.
                "dedupe_key": f"output-settlement-total:{output_jid}:{active_business_date}",
                "priority": 70,
                "business_date": active_business_date,
                "final_stage": "output_group_total",
                "depends_on": {"type": "output_wins", "output_jid": output_jid, "business_date": active_business_date},
            })
            # Also protects a total that was queued by an older build before
            # the dependency field existed.
            db.apply_final_dependencies(client_name, session_name, output_jid, active_business_date)
            counts["group_total_queued"] = True
        # Do not move to input groups halfway through this selected output
        # group.  This makes a 20-table final run appear as one uninterrupted
        # output settlement, followed only then by the customer statements.
        if counts["waiting_result"]:
            counts.update({
                "input_group_totals_queued": 0,
                "input_waiting_result": 0,
                "input_skipped": 0,
                "input_phase_held": True,
            })
            trace(
                f"[RUN FINAL] input phase held client={client_name} output_jid={output_jid} "
                f"waiting_result={counts['waiting_result']}"
            )
        else:
            counts.update(self._queue_input_group_totals(client_name, session_name, trigger_message_id, icons, limit * 10, active_business_date, output_jid))
            counts["input_phase_held"] = False
        trace(f"[RUN FINAL] queued client={client_name} output_jid={output_jid} date={active_business_date} counts={counts}")
        return counts


output_settlement_service = OutputSettlementService()
