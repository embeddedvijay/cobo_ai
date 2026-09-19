"""Safe local Result document helper retained for old HLA/result code."""
from datetime import datetime, time, timedelta
from pymongo import MongoClient
import os


def _date():
    now = datetime.now()
    if now.time() < time(0, 50):
        now -= timedelta(days=1)
    return now.strftime("%y-%m-%d")


def _db():
    return MongoClient(os.getenv("MONGODB_URL", "mongodb://127.0.0.1:27017/"))[os.getenv("MONGODB_DATABASE", "Market")][_date()]


def create_result_doc():
    _db().update_one({"Result": True}, {"$setOnInsert": {"Result": True}}, upsert=True)


def get_result_doc() -> dict:
    return _db().find_one({"Result": True}) or {}


def get_result_of_market(market: str) -> dict:
    return get_result_doc().get(market, {})


def i_op(market: str, open_value: str, opanal: str, otime: str | None = None):
    value = {"OPEN": str(open_value), "OPANAL": str(opanal)}
    if otime:
        value["OTIME"] = otime
    _db().update_one({"Result": True}, {"$set": {market: value}}, upsert=True)


def i_cl(market: str, close: str, cpanal: str, ctime: str | None = None):
    value = get_result_of_market(market)
    value.update({"CLOSE": str(close), "CPANAL": str(cpanal)})
    if ctime:
        value["CTIME"] = ctime
    _db().update_one({"Result": True}, {"$set": {market: value}}, upsert=True)
