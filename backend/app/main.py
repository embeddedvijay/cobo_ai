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


def desktop_collection(date: str):
    """Allow only the legacy Market/YY-MM-DD daily collections."""
    if not re.fullmatch(r"\d{2}-\d{2}-\d{2}", date or ""):
        raise HTTPException(status_code=422, detail="Date must be YY-MM-DD")
    return db.db[date]


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
    return sorted(names)


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
    base_query = {"Total": {"$exists": True}}
    if client_name:
        base_query["Client"] = client_name
    contacts = sorted(str(item) for item in collection.distinct("Contact", base_query) if item)
    query = dict(base_query)
    if contact:
        query["Contact"] = contact
    rows = []
    for row in collection.find(query).sort([("Time", 1), ("_id", 1)]):
        rows.append({
            "id": str(row["_id"]),
            "client": str(row.get("Client", "")),
            "contact": str(row.get("Contact", "")),
            "market": str(row.get("Market", "")),
            "time": str(row.get("Time", "")),
            "message": str(row.get("Message", "")),
            "total": int(row.get("Total", 0) or 0),
            "action": str(row.get("Action", "")),
            "settled": bool(row.get("Settled", False)),
        })
    return {"date": date, "contacts": contacts, "transactions": rows, "total_play": sum(item["total"] for item in rows)}


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
