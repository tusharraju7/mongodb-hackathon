"""Approved offer records: the system of record for rates, amounts, fees and conditions. Read-only."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.db import get_db


def get(offer_id: str, db=None) -> Optional[dict]:
    db = db if db is not None else get_db()
    return db.offers.find_one({"_id": offer_id})


def list_all(db=None) -> list[dict]:
    db = db if db is not None else get_db()
    return [serialize(o) for o in db.offers.find({}).sort("_id", 1)]


def serialize(offer: dict) -> dict:
    return {**{k: v for k, v in offer.items() if k != "_id"}, "id": offer["_id"]}


def is_valid(offer: dict, at: Optional[datetime] = None) -> bool:
    at = at or datetime.now(timezone.utc)
    start, end = offer.get("valid_from"), offer.get("valid_to")
    return (start is None or start <= at) and (end is None or end >= at)
