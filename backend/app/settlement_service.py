from __future__ import annotations

from datetime import datetime

from .database import db
from .settings import find_session


DEFAULT_RATES = {
    "ank": 9.5,
    "jodi": 95,
    "single_panna": 150,
    "double_panna": 300,
    "triple_panna": 600,
}


def _amount(value) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _money(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _panna_kind(value: str) -> str:
    if len(set(value)) == 1:
        return "triple_panna"
    if len(set(value)) == 2:
        return "double_panna"
    return "single_panna"


class SettlementService:
    """Settles each stored Message_ID against today's local Result document."""

    def _rates(self, client_name: str, session_name: str) -> dict:
        processing = find_session(client_name, session_name)["session"].get("processing", {})
        configured = processing.get("settlement_rates", {})
        return {key: float(configured.get(key, value)) for key, value in DEFAULT_RATES.items()}

    @staticmethod
    def _market_parts(market: str) -> tuple[str, str] | tuple[None, None]:
        if market.endswith("_OP"):
            return market[:-3], "OP"
        if market.endswith("_CL"):
            return market[:-3], "CL"
        return None, None

    @staticmethod
    def _result_values(base_market: str, side: str, result_doc: dict) -> dict | None:
        result = result_doc.get(base_market) or {}
        required = ("OPEN", "OPANAL", "CLOSE", "CPANAL")
        if not all(str(result.get(key, "")).strip() for key in required):
            return None
        open_value = str(result["OPEN"])
        close_value = str(result["CLOSE"])
        return {
            "ank": open_value if side == "OP" else close_value,
            "panna": str(result["OPANAL"] if side == "OP" else result["CPANAL"]),
            "jodi": f"{open_value}{close_value}",
            "display": f"{result['OPANAL']}-{open_value}{close_value}-{result['CPANAL']}",
        }

    @staticmethod
    def _winning_rows(transaction: dict, values: dict, rates: dict) -> list[dict]:
        wins = []
        for row in transaction.get("Result", []) or []:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            stake = _amount(row[-1])
            if stake <= 0:
                continue
            candidates = [str(item).strip() for item in row[:-1] if str(item).strip().isdigit()]
            choices = []
            for token in candidates:
                if len(token) == 1 and token == values["ank"]:
                    choices.append(("ank", token))
                elif len(token) == 2 and token == values["jodi"]:
                    choices.append(("jodi", token))
                elif len(token) == 3 and token == values["panna"]:
                    choices.append((_panna_kind(token), token))
            if choices:
                kind, token = max(choices, key=lambda choice: rates[choice[0]])
                wins.append({"number": token, "kind": kind, "stake": stake, "win": stake * rates[kind]})
        return wins

    @staticmethod
    def _reply(values: dict, wins: list[dict]) -> tuple[str, dict]:
        if not wins:
            return (
                f"❌ *RESULT: {values['display']}*\n*No Win*",
                {"result": values["display"], "wins": [], "total_win": 0},
            )
        lines = [f"✅ *RESULT: {values['display']}*", "*WIN*"]
        total = 0.0
        for win in wins:
            total += win["win"]
            lines.append(f"{win['number']} = ₹{_money(win['win'])}")
        lines.append(f"*TOTAL WIN = ₹{_money(total)}*")
        return "\n".join(lines), {"result": values["display"], "wins": wins, "total_win": total}

    def queue_pending(self, client_name: str, session_name: str, source_jid: str | None = None, limit: int = 1000) -> dict:
        rates = self._rates(client_name, session_name)
        counts = {"queued": 0, "waiting_result": 0, "skipped": 0}
        result_cache: dict[str, dict] = {}
        for raw in db.pending_settlements(client_name, session_name, source_jid, limit):
            if not db.reserve_settlement(raw["_id"]):
                continue
            transaction = db.legacy_transaction(raw)
            if not transaction:
                db.skip_settlement(raw["_id"], "legacy_transaction_not_found")
                counts["skipped"] += 1
                continue
            base_market, side = self._market_parts(str(transaction.get("Market", "")))
            if not base_market:
                db.skip_settlement(raw["_id"], "unsupported_market")
                counts["skipped"] += 1
                continue
            result_doc = result_cache.setdefault(raw["business_date"], db.result_document(raw["business_date"]))
            values = self._result_values(base_market, side, result_doc)
            if not values:
                # Result has not arrived yet. Keep this message eligible for the
                # next end trigger; never label it as a no-win prematurely.
                db.release_settlement(raw["_id"])
                counts["waiting_result"] += 1
                continue
            reply, details = self._reply(values, self._winning_rows(transaction, values, rates))
            db.enqueue({
                "client_name": raw["client_name"],
                "session_name": raw["session_name"],
                "channel": "whatsapp",
                "target": raw["source_jid"],
                "text": reply,
                "quote": raw["raw_message"],
                "kind": "settlement_source_reply",
                "raw_id": raw["_id"],
                "dedupe_key": f"settlement:{raw['_id']}",
            })
            db.mark_settlement_queued(raw["_id"], details)
            counts["queued"] += 1
        return counts


settlement_service = SettlementService()
