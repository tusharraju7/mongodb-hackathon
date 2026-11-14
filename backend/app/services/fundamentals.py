"""Policy clauses: reads for the review, and the versioned, step-up-protected update."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core import embeddings, gate, security
from app.core.db import get_db, oid
from app.models import Identity

NO_VECTOR = {"embedding": 0}


class NotFound(Exception):
    pass


def clause_document(clause: dict) -> str:
    """The text that is embedded for a clause. The seed script must embed exactly this."""
    return f"{clause['title']}. {clause['text']}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def in_effect_filter(regions: list[str], product: str, at: Optional[datetime] = None) -> dict:
    at = at or _now()
    return {
        "status": "approved",
        "region": {"$in": regions},
        "product": {"$in": [product, "all"]},
        "effective_from": {"$lte": at},
        "$or": [{"effective_to": None}, {"effective_to": {"$gte": at}}],
    }


def applicable(regions: list[str], product: str, db=None) -> list[dict]:
    db = db if db is not None else get_db()
    return list(db.fundamentals.find(in_effect_filter(regions, product), NO_VECTOR))


def similar(vectors: list[list[float]], regions: list[str], product: str, k: int, db=None) -> list[list[tuple[dict, float]]]:
    """For each query vector, the closest approved clauses for this product and region, with cosine similarity."""
    db = db if db is not None else get_db()
    at = _now()
    out = []
    for vector in vectors:
        pipeline = [
            {"$vectorSearch": {
                "index": "fundamentals_vec", "path": "embedding", "queryVector": vector, "numCandidates": 60, "limit": k + 3,
                "filter": {"status": "approved", "region": {"$in": regions}, "product": {"$in": [product, "all"]}},
            }},
            {"$set": {"_score": {"$meta": "vectorSearchScore"}}},
            {"$project": NO_VECTOR},
        ]
        hits = []
        for doc in db.fundamentals.aggregate(pipeline):
            start, end = doc.get("effective_from"), doc.get("effective_to")
            if (start is None or start <= at) and (end is None or end >= at):
                # Atlas reports cosine as (1 + cos) / 2; the review works in plain cosine.
                hits.append((doc, 2 * doc.pop("_score") - 1))
        out.append(hits[:k])
    return out


def list_all(identity: Identity, db=None) -> list[dict]:
    db = db if db is not None else get_db()
    return [serialize(c) for c in db.fundamentals.find({}, NO_VECTOR).sort("key", 1)]


def serialize(clause: dict) -> dict:
    out = {k: v for k, v in clause.items() if k != "embedding"}
    out["id"] = str(out.pop("_id"))
    return out


def get(fundamental_id: str, db=None) -> dict:
    db = db if db is not None else get_db()
    clause = db.fundamentals.find_one({"_id": oid(fundamental_id)}, NO_VECTOR) or db.fundamentals.find_one({"key": fundamental_id}, NO_VECTOR)
    if not clause:
        raise NotFound(f"No policy clause {fundamental_id}")
    return clause


def history(fundamental_id: str, db=None) -> list[dict]:
    db = db if db is not None else get_db()
    clause = get(fundamental_id, db)
    rows = db.fundamentals_versions.find({"key": clause["key"]}).sort("version", -1)
    return [{**{k: v for k, v in r.items() if k not in ("_id", "fundamental_id")}, "id": str(r["_id"])} for r in rows]


def current_versions(keys: list[str], db=None) -> dict[str, Optional[int]]:
    """Version of each clause as it stands now. None means it is no longer approved or in effect."""
    db = db if db is not None else get_db()
    at = _now()
    out: dict[str, Optional[int]] = {k: None for k in keys}
    for c in db.fundamentals.find({"key": {"$in": keys}}, {"key": 1, "version": 1, "status": 1, "effective_from": 1, "effective_to": 1}):
        live = c.get("status") == "approved" and (c.get("effective_from") is None or c["effective_from"] <= at) and (c.get("effective_to") is None or c["effective_to"] >= at)
        out[c["key"]] = c.get("version", 1) if live else None
    return out


def update(identity: Identity, run_id: str, fundamental_id: str, *, text: str, reason: str, password: Optional[str], rule: Optional[dict] = None, summary: Optional[str] = None, db=None) -> dict:
    """Change a clause. Asks for the password every time, keeps the old version, and records before and after."""
    db = db if db is not None else get_db()
    before = get(fundamental_id, db)
    params = {"key": before["key"], "from_version": before.get("version", 1), "reason": reason, "before": before["text"], "after": text}

    if not gate.permitted(identity, "fundamentals.update", db):
        # Let the gate record the denial and raise.
        gate.guarded(identity, "fundamentals.update", params, run_id, lambda: None, db=db)
    if not security.verify_password(identity, password, db):
        gate.record_denial(identity, "fundamentals.update", params, run_id, "step-up password missing or wrong", db=db)
        raise security.StepUpFailed("This change needs your password, and the one given was missing or wrong.")

    def apply() -> dict:
        new_version = before.get("version", 1) + 1
        changed = {**before, "text": text, "summary": summary or before.get("summary", "")}
        if rule is not None:
            changed["rule"] = rule
        vector = embeddings.embed_documents([clause_document(changed)])[0]
        db.fundamentals_versions.insert_one({
            "fundamental_id": before["_id"], "key": before["key"], "version": before.get("version", 1),
            "snapshot": {k: v for k, v in before.items() if k != "_id"},
            "replaced_by": identity.user_id, "replaced_at": _now(), "reason": reason,
        })
        fields = {"text": text, "summary": changed["summary"], "version": new_version, "embedding": vector, "updated_by": identity.user_id, "updated_at": _now()}
        if rule is not None:
            fields["rule"] = rule
        db.fundamentals.update_one({"_id": before["_id"]}, {"$set": fields})
        return get(str(before["_id"]), db)

    after = gate.guarded(
        identity, "fundamentals.update", params, run_id, apply,
        auth_method="jwt+password",
        undo={"type": "fundamental.restore", "ref": {"key": before["key"], "version": before.get("version", 1)}},
        policy_refs=[{"key": before["key"], "version": before.get("version", 1)}],
        summarize=lambda c: {"status": "ok", "summary": f"{c['key']} changed from version {before.get('version', 1)} to {c['version']}", "ref": {"collection": "fundamentals", "id": str(c["_id"])}},
        db=db,
    )
    return serialize(after)


def restore(key: str, version: int, actor: Identity, db=None) -> dict:
    """Put a clause back to an earlier version, number included.

    The content is identical to what that version number meant, so approvals that were bound to it
    are valid again. The version being replaced is kept in the history.
    """
    db = db if db is not None else get_db()
    current = db.fundamentals.find_one({"key": key})
    snap = db.fundamentals_versions.find_one({"key": key, "version": version}, sort=[("replaced_at", -1)])
    if not current or not snap:
        raise NotFound(f"No stored version {version} of {key}")
    old = snap["snapshot"]
    db.fundamentals_versions.insert_one({
        "fundamental_id": current["_id"], "key": key, "version": current.get("version", 1),
        "snapshot": {k: v for k, v in current.items() if k not in ("_id", "embedding")},
        "replaced_by": actor.user_id, "replaced_at": _now(), "reason": f"rollback to version {version}",
    })
    restored = {**current, **{k: old[k] for k in ("text", "summary", "rule") if k in old}}
    fields = {
        "text": old["text"], "summary": old.get("summary", ""), "version": version,
        "embedding": old.get("embedding") or embeddings.embed_documents([clause_document(restored)])[0],
        "updated_by": actor.user_id, "updated_at": _now(),
    }
    update = {"$set": fields}
    if "rule" in old:
        fields["rule"] = old["rule"]
    elif "rule" in current:
        update["$unset"] = {"rule": ""}
    db.fundamentals.update_one({"_id": current["_id"]}, update)
    return serialize(db.fundamentals.find_one({"_id": current["_id"]}, NO_VECTOR))
