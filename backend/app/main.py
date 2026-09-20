from __future__ import annotations

from bson import ObjectId
from fastapi import FastAPI, Header, HTTPException, Query
from datetime import datetime
import re
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .database import db
from .legacy_engine import engine
from .output_settlement_service import output_settlement_service
from .settlement_service import settlement_service
from .settings import bridge_secret, find_session

app = FastAPI(title="Dust Legacy Operations + Baileys Bridge")


def api_response(payload):
    """MongoDB ObjectId can exist in a durable outbox/raw payload.

    Convert it before FastAPI serialises a response; otherwise an already
    processed message wrongly becomes an HTTP 500 for the Baileys bridge.
    """
    return JSONResponse(content=jsonable_encoder(payload, custom_encoder={ObjectId: str}))


class Incoming(BaseModel):
    client_name: str
    session_name: str
    source_jid: str
    source_name: str | None = None
    message_id: str
    participant: str | None = None
    text: str
    message_timestamp: int | None = None
    quoted_text: str = ""
    quoted_message_id: str | None = None
    raw_message: dict


class OutputTrigger(BaseModel):
    client_name: str
    session_name: str
    output_jid: str
    message_id: str
    text: str


class GroupMapping(BaseModel):
    group_name: str
    group_name_key: str
    jid: str
    roles: list[str] = []


class GroupMappingsSync(BaseModel):
    client_name: str
    session_name: str
    mappings: list[GroupMapping]


class ResultEditorUpdate(BaseModel):
    date: str
    market: str
    open: str = ""
    open_panna: str = ""
    close: str = ""
    close_panna: str = ""
    open_time: str = ""
    close_time: str = ""


class TransactionEditorUpdate(BaseModel):
    date: str
    record_id: str
    message: str | None = None
    total: int | None = None


class TransactionReject(BaseModel):
    date: str
    record_id: str


class ManualFinalRequest(BaseModel):
    client_name: str
    session_name: str = "_runtime"
    output_group: str


def configured_output_groups(client_name: str, session_name: str) -> list[str]:
    try:
        contacts = find_session(client_name, session_name)["session"].get("out_contacts", {})
    except KeyError:
        return []
    groups = set()
    for route in contacts.values():
        if not isinstance(route, dict):
            continue
        for value in route.values():
            if isinstance(value, str) and value.strip():
                groups.add(value.strip())
            elif isinstance(value, list):
                groups.update(str(item).strip() for item in value if str(item).strip())
    return sorted(groups)


def desktop_collection(date: str):
    """Allow only the legacy Market/YY-MM-DD daily collections."""
    if not re.fullmatch(r"\d{2}-\d{2}-\d{2}", date or ""):
        raise HTTPException(status_code=422, detail="Date must be YY-MM-DD")
    return db.db[date]


@app.get("/desktop/output-groups")
def desktop_output_groups(client_name: str = Query(""), session_name: str = Query("_runtime")):
    return {"groups": db.available_output_groups(client_name, session_name)}


@app.get("/desktop/resolve-output-group")
def desktop_resolve_output_group(name: str = Query(""), client_name: str = Query(""), session_name: str = Query("_runtime")):
    return db.resolve_output_group_name(client_name, session_name, name)


@app.get("/desktop/group-mappings")
def desktop_group_mappings(client_name: str = Query(""), session_name: str = Query("_runtime")):
    return {"mappings": db.resolved_group_mappings(client_name, session_name)}


def desktop_market_names(client_name: str, session_name: str, result_doc: dict) -> list[str]:
    names = set()
    try:
        timings = find_session(client_name, session_name)["session"].get("market_timings", {})
        for key in timings:
            names.add(re.sub(r"_(OP|CL)$", "", str(key)))
    except KeyError:
        pass
    for key, value in result_doc.items():
        if key not in {"_id", "Result"} and isinstance(value, dict):
            names.add(str(key))
    # Result board stays in the operator's familiar market-family order while
    # retaining every configured DAY/NIGHT variant as one OP+CL result card.
    family_order = ("SRIDEVI", "TIME_BAZAR", "MAIN_BAZAR", "MADHUR", "MILAN", "RAJDHANI", "SUPREME", "KALYAN")
    def market_order(name: str):
        upper = str(name).upper()
        index = next((i for i, family in enumerate(family_order) if upper.startswith(family)), len(family_order))
        return (index, upper)
    return sorted(names, key=market_order)


def _money_amount(value) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _dashboard_result_values(base_market: str, side: str, result_doc: dict) -> dict | None:
    """Dashboard may show OP/CL win as soon as that side's result arrives.

    Final WhatsApp settlement deliberately still waits for the full result.
    """
    result = result_doc.get(base_market) or {}
    open_ank = str(result.get("OPEN", "")).strip()
    open_panna = str(result.get("OPANAL", result.get("OP_PANAL", ""))).strip()
    close_ank = str(result.get("CLOSE", "")).strip()
    close_panna = str(result.get("CPANAL", result.get("CL_PANAL", ""))).strip()
    if side == "OP":
        if not open_ank or not open_panna:
            return None
        return {"ank": open_ank, "panna": open_panna, "jodi": f"{open_ank}{close_ank}" if close_ank else ""}
    if side == "CL":
        if not close_ank or not close_panna:
            return None
        return {"ank": close_ank, "panna": close_panna, "jodi": f"{open_ank}{close_ank}" if open_ank else ""}
    return None


def _dashboard_win(transaction: dict, result_doc: dict, rates: dict) -> int:
    base_market, side = settlement_service._market_parts(str(transaction.get("Market", "")))
    if not base_market:
        return 0
    values = _dashboard_result_values(base_market, side, result_doc)
    if not values:
        return 0
    return _money_amount(sum(item.get("win", 0) for item in settlement_service._winning_rows(transaction, values, rates)))


def _market_play_breakdown(rows: list[dict], market: str, result_doc: dict, rates: dict) -> dict:
    """Aggregate one customer's market into the desktop Ank/Panna/Jodi view."""
    number_table: dict[str, int] = {}
    breakdown = {
        "OP": {"play": 0, "win": 0, "ank": {"play": 0, "win": 0}, "panna": {"play": 0, "win": 0}, "jodi": {"play": 0, "win": 0}, "winning_numbers": {"ank": {}, "panna": {}, "jodi": {}}},
        "CL": {"play": 0, "win": 0, "ank": {"play": 0, "win": 0}, "panna": {"play": 0, "win": 0}, "jodi": {"play": 0, "win": 0}, "winning_numbers": {"ank": {}, "panna": {}, "jodi": {}}},
    }
    for row in rows:
        base_market, side = settlement_service._market_parts(str(row.get("Market", "")))
        if base_market != market or side not in breakdown:
            continue
        total = _money_amount(row.get("Total"))
        breakdown[side]["play"] += total
        values = _dashboard_result_values(base_market, side, result_doc)
        wins = settlement_service._winning_rows(row, values, rates) if values else []
        breakdown[side]["win"] += _money_amount(sum(item.get("win", 0) for item in wins))
        for winner in wins:
            kind = "panna" if "panna" in str(winner.get("kind", "")) else str(winner.get("kind", ""))
            if kind not in breakdown[side]:
                continue
            breakdown[side][kind]["win"] += _money_amount(winner.get("win", 0))
            number = str(winner.get("number", ""))
            item = breakdown[side]["winning_numbers"][kind].setdefault(number, {"number": number, "stake": 0, "win": 0})
            item["stake"] += _money_amount(winner.get("stake", 0))
            item["win"] += _money_amount(winner.get("win", 0))
        for bet in row.get("Result", []) or []:
            if not isinstance(bet, (list, tuple)) or len(bet) < 2:
                continue
            amount = _money_amount(bet[-1])
            for token in bet[:-1]:
                token = str(token).strip()
                if token.isdigit() and 1 <= len(token) <= 3:
                    number_table[token] = number_table.get(token, 0) + amount
                    kind = "ank" if len(token) == 1 else "jodi" if len(token) == 2 else "panna"
                    breakdown[side][kind]["play"] += amount
    for side in breakdown.values():
        side["winning_numbers"] = {
            kind: sorted(numbers.values(), key=lambda item: item["number"])
            for kind, numbers in side["winning_numbers"].items()
        }
    return {"number_table": dict(sorted(number_table.items(), key=lambda item: (len(item[0]), item[0]))), "breakdown": breakdown}


@app.get("/desktop/dashboard")
def desktop_dashboard(
    date: str = Query(...),
    client_name: str = Query(""),
    session_name: str = Query("_runtime"),
    market: str = Query(""),
    contact: str = Query(""),
):
    """Live operations view: customer play/win, messages, market totals and table."""
    collection = desktop_collection(date)
    query = {"Total": {"$exists": True}, "Deleted": {"$ne": True}}
    if client_name:
        query["Client"] = client_name
    result_doc = collection.find_one({"Result": True}) or {}
    try:
        rates = settlement_service._rates(client_name, session_name)
    except Exception:
        rates = {"ank": 9.5, "jodi": 95, "single_panna": 150, "double_panna": 300, "triple_panna": 600}
    all_rows = list(collection.find(query).sort([("Time", 1), ("_id", 1)]))
    customers: dict[str, dict] = {}
    for row in all_rows:
        row_contact = str(row.get("Contact", ""))
        name = db.group_name_for_jid(client_name, session_name, row_contact) or row_contact
        customer = customers.setdefault(row_contact, {"name": name, "contact": row_contact, "play": 0, "win": 0, "messages": 0})
        total = _money_amount(row.get("Total"))
        win = _dashboard_win(row, result_doc, rates)
        customer["play"] += total; customer["win"] += win; customer["messages"] += 1

    selected_contact = contact
    rows = [row for row in all_rows if not selected_contact or str(row.get("Contact", "")) == selected_contact]
    markets: dict[str, dict] = {}
    for row in rows:
        market_name = str(row.get("Market", "") or "UNKNOWN")
        base_market, side = settlement_service._market_parts(market_name)
        market_name = base_market or market_name
        total = _money_amount(row.get("Total"))
        win = _dashboard_win(row, result_doc, rates)
        market_row = markets.setdefault(market_name, {
            "market": market_name, "play": 0, "win": 0, "messages": 0,
            "open_play": 0, "open_win": 0, "close_play": 0, "close_win": 0,
        })
        market_row["play"] += total; market_row["win"] += win; market_row["messages"] += 1
        if side == "OP":
            market_row["open_play"] += total; market_row["open_win"] += win
        elif side == "CL":
            market_row["close_play"] += total; market_row["close_win"] += win

    selected_base, _ = settlement_service._market_parts(market)
    selected = selected_base or market or (next(reversed(markets)) if markets else "")
    number_table: dict[str, int] = {}
    breakdown = {
        "OP": {"play": 0, "win": 0, "ank": {"play": 0, "win": 0}, "panna": {"play": 0, "win": 0}, "jodi": {"play": 0, "win": 0}, "winning_numbers": {"ank": {}, "panna": {}, "jodi": {}}},
        "CL": {"play": 0, "win": 0, "ank": {"play": 0, "win": 0}, "panna": {"play": 0, "win": 0}, "jodi": {"play": 0, "win": 0}, "winning_numbers": {"ank": {}, "panna": {}, "jodi": {}}},
    }
    for row in rows:
        row_market = str(row.get("Market", ""))
        base_market, side = settlement_service._market_parts(row_market)
        if (base_market or row_market) != selected:
            continue
        if side not in breakdown:
            continue
        total = _money_amount(row.get("Total"))
        breakdown[side]["play"] += total
        values = _dashboard_result_values(base_market, side, result_doc) if base_market else None
        wins = settlement_service._winning_rows(row, values, rates) if values else []
        breakdown[side]["win"] += _money_amount(sum(item.get("win", 0) for item in wins))
        for winner in wins:
            kind = "panna" if "panna" in winner["kind"] else winner["kind"]
            if kind in breakdown[side]:
                breakdown[side][kind]["win"] += _money_amount(winner.get("win", 0))
                number = str(winner.get("number", ""))
                item = breakdown[side]["winning_numbers"][kind].setdefault(number, {"number": number, "stake": 0, "win": 0})
                item["stake"] += _money_amount(winner.get("stake", 0))
                item["win"] += _money_amount(winner.get("win", 0))
        for bet in row.get("Result", []) or []:
            if not isinstance(bet, (list, tuple)) or len(bet) < 2:
                continue
            amount = _money_amount(bet[-1])
            for token in bet[:-1]:
                token = str(token).strip()
                if token.isdigit() and 1 <= len(token) <= 3:
                    number_table[token] = number_table.get(token, 0) + amount
                    kind = "ank" if len(token) == 1 else "jodi" if len(token) == 2 else "panna"
                    breakdown[side][kind]["play"] += amount
    for side in breakdown.values():
        side["winning_numbers"] = {
            kind: sorted(numbers.values(), key=lambda item: item["number"])
            for kind, numbers in side["winning_numbers"].items()
        }
    messages = []
    for row in rows[-30:][::-1]:
        row_contact = str(row.get("Contact", ""))
        messages.append({
            "id": str(row.get("_id")), "market": str(row.get("Market", "")),
            "group": db.group_name_for_jid(client_name, session_name, row_contact) or row_contact,
            "time": str(row.get("Time", "")), "message": str(row.get("Message", "")),
            "total": _money_amount(row.get("Total")), "win": _dashboard_win(row, result_doc, rates),
        })
    return {
        "date": date,
        "total_play": sum(item["play"] for item in customers.values()),
        "total_win": sum(item["win"] for item in customers.values()),
        "customers": sorted(customers.values(), key=lambda item: item["play"], reverse=True),
        "selected_contact": selected_contact,
        "markets": sorted(markets.values(), key=lambda item: item["play"], reverse=True),
        "selected_market": selected,
        "number_table": dict(sorted(number_table.items(), key=lambda item: (len(item[0]), item[0]))),
        "breakdown": breakdown,
        "messages": messages,
    }


@app.get("/desktop/final-options")
def desktop_final_options(client_name: str = Query(""), session_name: str = Query("_runtime")):
    return {"output_groups": configured_output_groups(client_name, session_name)}


@app.post("/desktop/run-final")
def desktop_run_final(payload: ManualFinalRequest):
    """Manual equivalent of the output-group `last` trigger from Dashboard."""
    output_name = payload.output_group.strip()
    if output_name not in configured_output_groups(payload.client_name, payload.session_name):
        raise HTTPException(status_code=422, detail="Select a configured output group")
    output_jid = output_name if output_name.endswith("@g.us") else db.group_jid_for_name(
        payload.client_name, payload.session_name, output_name
    )
    if not output_jid:
        raise HTTPException(status_code=409, detail="Output group is not resolved yet. Start the service once, then retry.")
    trigger_id = f"desktop-final:{db.date}:{output_jid}"
    return api_response(output_settlement_service.queue_group(
        payload.client_name, payload.session_name, output_jid, trigger_id
    ))


def verify(secret: str | None) -> None:
    expected = bridge_secret()
    if expected and secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized bridge")


def capture(payload: Incoming):
    doc = payload.model_dump()
    doc["source_name"] = doc["source_name"] or db.group_name_for_jid(
        payload.client_name, payload.session_name, payload.source_jid
    ) or doc["source_jid"]
    doc["state"] = "received"
    return db.capture_raw(doc)


def run_pending(client_name: str, session_name: str, source_jid: str | None = None, limit: int = 1000):
    counts = {"processed": 0, "errors": 0}
    for _ in range(limit):
        raw = db.claim_next_pending(client_name, session_name, source_jid)
        if not raw:
            break
        try:
            outcome = engine.process_one(raw)
            counts[outcome["status"]] += 1
        except Exception as exc:
            db.mark_raw(raw["_id"], "error", error=str(exc))
            counts["errors"] += 1
            print(f"Legacy processor error for {raw['message_id']}: {exc}", flush=True)
    return counts


def queue_final_replies(client_name: str, session_name: str, source_jid: str | None = None, limit: int = 1000):
    """End mode: settlement based on local MongoDB Result, never a duplicate ✅."""
    return settlement_service.queue_pending(client_name, session_name, source_jid, limit)


@app.get("/health")
def health():
    return {"ok": True, "engine": "legacy operations + baileys"}


@app.get("/desktop/results")
def desktop_results(
    date: str = Query(...),
    client_name: str = Query(""),
    session_name: str = Query("_runtime"),
):
    """Date-wise market results for the desktop workspace."""
    collection = desktop_collection(date)
    result_doc = collection.find_one({"Result": True}) or {"Result": True}
    markets = []
    for market in desktop_market_names(client_name, session_name, result_doc):
        row = result_doc.get(market) or {}
        markets.append({
            "market": market,
            "open": str(row.get("OPEN", "")),
            "open_panna": str(row.get("OPANAL", row.get("OP_PANAL", ""))),
            "close": str(row.get("CLOSE", "")),
            "close_panna": str(row.get("CPANAL", row.get("CL_PANAL", ""))),
            "open_time": str(row.get("OTIME", "")),
            "close_time": str(row.get("CTIME", "")),
        })
    return {"date": date, "markets": markets}


@app.put("/desktop/results")
def save_desktop_result(payload: ResultEditorUpdate):
    collection = desktop_collection(payload.date)
    current = collection.find_one({"Result": True}, {payload.market: 1}) or {}
    value = dict(current.get(payload.market) or {})
    value.update({
        "OPEN": payload.open.strip(),
        "OPANAL": payload.open_panna.strip(),
        "CLOSE": payload.close.strip(),
        "CPANAL": payload.close_panna.strip(),
        "OTIME": payload.open_time.strip(),
        "CTIME": payload.close_time.strip(),
    })
    collection.update_one({"Result": True}, {"$setOnInsert": {"Result": True}, "$set": {payload.market: value}}, upsert=True)
    return {"ok": True, "market": payload.market, "date": payload.date}


@app.get("/desktop/transactions")
def desktop_transactions(
    date: str = Query(...),
    client_name: str = Query(""),
    contact: str = Query(""),
):
    """Daily customer history; each row represents one parsed input message."""
    collection = desktop_collection(date)
    result_doc = collection.find_one({"Result": True}) or {}
    try:
        rates = settlement_service._rates(client_name, "_runtime")
    except Exception:
        rates = {"ank": 9.5, "jodi": 95, "single_panna": 150, "double_panna": 300, "triple_panna": 600}
    base_query = {"Total": {"$exists": True}, "Deleted": {"$ne": True}}
    if client_name:
        base_query["Client"] = client_name
    contacts = sorted(str(item) for item in collection.distinct("Contact", base_query) if item)
    # Legacy records store the WhatsApp JID in Contact. The bridge separately
    # persists its configured display name, which we use only for the UI.
    contact_names = {
        item: db.group_name_for_jid(client_name, "_runtime", item) or item
        for item in contacts
    }
    query = dict(base_query)
    if contact:
        query["Contact"] = contact
    raw_rows = list(collection.find(query).sort([("Time", 1), ("_id", 1)]))
    rows = []
    for row in raw_rows:
        base_market, side = settlement_service._market_parts(str(row.get("Market", "")))
        result_ready = bool(base_market and settlement_service._result_values(base_market, side, result_doc))
        rows.append({
            "id": str(row["_id"]),
            "client": str(row.get("Client", "")),
            "contact": str(row.get("Contact", "")),
            "contact_name": contact_names.get(str(row.get("Contact", "")), str(row.get("Contact", ""))),
            "market": str(row.get("Market", "")),
            "time": str(row.get("Time", "")),
            "message": str(row.get("Message", "")),
            "total": int(row.get("Total", 0) or 0),
            "win": _dashboard_win(row, result_doc, rates),
            "action": str(row.get("Action", "")),
            "settled": bool(row.get("Settled", False)),
            "result_ready": result_ready,
        })
    market_names = sorted({settlement_service._market_parts(str(row.get("Market", "")))[0] for row in raw_rows if settlement_service._market_parts(str(row.get("Market", "")))[0]})
    market_details = {
        market: _market_play_breakdown(raw_rows, market, result_doc, rates)
        for market in market_names
    }
    return {
        "date": date,
        "contacts": [{"value": item, "name": contact_names[item]} for item in contacts],
        "transactions": rows,
        "market_details": market_details,
        "total_play": sum(item["total"] for item in rows),
    }


@app.put("/desktop/transactions")
def save_desktop_transaction(payload: TransactionEditorUpdate):
    from bson import ObjectId
    collection = desktop_collection(payload.date)
    try:
        record_id = ObjectId(payload.record_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid transaction record") from exc
    changes = {}
    if payload.message is not None:
        changes["Message"] = payload.message
    if payload.total is not None:
        changes["Total"] = int(payload.total)
    if not changes:
        return {"ok": True, "changed": False}
    changed = collection.update_one({"_id": record_id, "Total": {"$exists": True}}, {"$set": changes})
    if not changed.matched_count:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"ok": True, "changed": bool(changed.modified_count)}


@app.post("/desktop/transactions/reject")
def reject_desktop_transaction(payload: TransactionReject):
    """Remove one accepted play from all totals without allowing replay after restart."""
    collection = desktop_collection(payload.date)
    try:
        record_id = ObjectId(payload.record_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid transaction record") from exc
    transaction = collection.find_one({"_id": record_id, "Total": {"$exists": True}, "Deleted": {"$ne": True}})
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction was already removed")
    now = datetime.utcnow()
    collection.update_one(
        {"_id": record_id},
        {"$set": {"Deleted": True, "Settled": True, "RejectedAt": now, "RejectedBy": "desktop"}},
    )
    message_id = str(transaction.get("Message_ID", ""))
    client_name = str(transaction.get("Client", ""))
    if message_id:
        db.raw.update_many(
            {"client_name": client_name, "session_name": "_runtime", "message_id": message_id},
            {"$set": {
                "state": "cancelled", "normal_state": "cancelled", "settlement_state": "skipped",
                "final_reply_state": "skipped", "operator_rejected_at": now,
            }},
        )
    return {"ok": True, "record_id": payload.record_id}


@app.get("/status/{client_name}/{session_name}")
def status(client_name: str, session_name: str, x_bridge_secret: str | None = Header(default=None)):
    """Small operational view: useful to verify start/end batch and recovery."""
    verify(x_bridge_secret)
    rows = db.raw.aggregate([
        {"$match": {"client_name": client_name, "session_name": session_name}},
        {"$group": {"_id": "$state", "count": {"$sum": 1}}},
    ])
    settlements = db.raw.aggregate([
        {"$match": {"client_name": client_name, "session_name": session_name}},
        {"$group": {"_id": "$settlement_state", "count": {"$sum": 1}}},
    ])
    outbox = db.outbox.aggregate([
        {"$match": {"client_name": client_name, "session_name": session_name}},
        {"$group": {"_id": "$state", "count": {"$sum": 1}}},
    ])
    return {
        "states": {row["_id"]: row["count"] for row in rows},
        "settlements": {str(row["_id"] or "pending"): row["count"] for row in settlements},
        "outbox": {str(row["_id"] or "pending"): row["count"] for row in outbox},
    }


@app.post("/incoming")
def incoming(payload: Incoming, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    try:
        meta = find_session(payload.client_name, payload.session_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raw, inserted = capture(payload)
    if not inserted:
        return api_response({"status": "duplicate", "state": raw.get("state")})
    # One incoming event must drain every older pending row of this same group.
    # A previous transient 500/restart can otherwise leave one row at the head
    # of the FIFO queue and make all new live messages appear frozen forever.
    # Node and the HLA worker already serialise this source, so this preserves
    # exact group order while recovering its backlog in the same request.
    return api_response(run_pending(payload.client_name, payload.session_name, payload.source_jid, limit=1000))


@app.post("/groups/sync")
def groups_sync(payload: GroupMappingsSync, x_bridge_secret: str | None = Header(default=None)):
    """Store the current connected-account name → JID resolution.

    Config users enter only group names. Baileys is the source of truth for the
    JID because a group can be recreated with the same display name.
    """
    verify(x_bridge_secret)
    find_session(payload.client_name, payload.session_name)
    count = db.sync_group_mappings(
        payload.client_name,
        payload.session_name,
        [item.model_dump() for item in payload.mappings],
    )
    return {"ok": True, "mapped": count}


@app.post("/settlement/output-trigger")
def output_trigger(payload: OutputTrigger, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    meta = find_session(payload.client_name, payload.session_name)
    trigger = str(meta["session"].get("processing", {}).get("trigger_contains", "last")).strip().lower()
    if payload.text.strip().lower() != trigger:
        raise HTTPException(status_code=400, detail="Output trigger text does not match")
    return api_response(output_settlement_service.queue_group(payload.client_name, payload.session_name, payload.output_jid, payload.message_id))


@app.post("/replay/{client_name}/{session_name}")
def replay(client_name: str, session_name: str, source_jid: str | None = None, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    return api_response(queue_final_replies(client_name, session_name, source_jid))


@app.post("/outbox/{message_id}/delivery")
def outbox_delivery(message_id: str, payload: dict, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    db.mark_outbox_delivery(message_id, str(payload["target_jid"]), payload["sent_message"])
    return {"ok": True}


@app.post("/outbox/{message_id}/attempt")
def outbox_attempt(message_id: str, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    if not db.mark_outbox_send_attempt(message_id):
        raise HTTPException(status_code=409, detail="Outbox item is not available for send")
    return {"ok": True}


@app.post("/outbox/{message_id}/uncertain")
def outbox_uncertain(message_id: str, error: str = "", x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    db.mark_outbox_uncertain(message_id, error)
    return {"ok": True}


@app.post("/outbox/{message_id}/resolve")
def resolve_outbox(message_id: str, sent: bool, x_bridge_secret: str | None = Header(default=None)):
    """After checking the output group: sent=true closes it, sent=false retries it."""
    verify(x_bridge_secret)
    db.resolve_outbox_uncertain(message_id, sent)
    return {"ok": True}


@app.post("/outbox/claim")
def claim_outbox(client_name: str, session_name: str, limit: int = 50, x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    return api_response({"items": db.claim_outbox(client_name, session_name, min(max(limit, 1), 200))})


@app.post("/outbox/{message_id}/result")
def outbox_result(message_id: str, sent: bool, error: str = "", x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    db.outbox_result(message_id, sent, error)
    return {"ok": True}


@app.post("/outbox/{message_id}/invalid-target")
def outbox_invalid_target(message_id: str, error: str = "", x_bridge_secret: str | None = Header(default=None)):
    verify(x_bridge_secret)
    db.mark_outbox_invalid_target(message_id, error or "Unknown WhatsApp output group")
    return {"ok": True}
