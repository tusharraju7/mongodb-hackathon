"""Governed memory: scoped recall, and gated writes that keep history.

Who may read a memory is decided in the query, never in a prompt:
  - it belongs to the caller's team,
  - the caller's role is in its visibility list,
  - it is active and not expired,
  - and, if it is a personal note, the caller is its owner.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core import embeddings, gate
from app.core.db import get_db, oid
from app.models import Identity

NO_VECTOR = {"embedding": 0}
DEFAULT_VISIBILITY = ["manager", "marketer"]
EPISODIC_TTL_DAYS = 30


class NotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def serialize(memory: dict) -> dict:
    out = {k: v for k, v in memory.items() if k != "embedding"}
    out["id"] = str(out.pop("_id"))
    for key in ("supersedes",):
        if out.get(key) is not None:
            out[key] = str(out[key])
    return out


def _readable(memory: dict, identity: Identity, at: datetime) -> bool:
    scope = memory.get("scope") or {}
    expires = memory.get("expires_at")
    return (
        scope.get("team") == identity.team
        and identity.role in memory.get("visibility_roles", [])
        and memory.get("status") == "active"
        and (expires is None or expires > at)
        and scope.get("user_id") in (None, identity.user_id)
    )


def recall_by_vector(identity: Identity, vector: list[float], kinds: list[str], k: int = 3, db=None) -> list[dict]:
    """The closest memories this caller may read. Team, role, status and kind are filters inside the search."""
    db = db if db is not None else get_db()
    at = _now()
    pipeline = [
        {"$vectorSearch": {
            "index": "memories_vec", "path": "embedding", "queryVector": vector, "numCandidates": 80, "limit": k * 4,
            "filter": {"status": "active", "scope.team": identity.team, "visibility_roles": identity.role, "kind": {"$in": kinds}},
        }},
        {"$project": NO_VECTOR},
    ]
    # Expiry and personal-note ownership are checked here as well: the TTL monitor only runs about
    # once a minute, and a personal note must never reach anyone but its owner.
    hits = [m for m in db.memories.aggregate(pipeline) if _readable(m, identity, at)][:k]
    if hits:
        db.memories.update_many({"_id": {"$in": [m["_id"] for m in hits]}}, {"$inc": {"use_count": 1}, "$set": {"last_used_at": at}})
    return [{"id": str(m["_id"]), "kind": m["kind"], "text": m["text"]} for m in hits]


def recall(identity: Identity, query: str, *, kinds: list[str], k: int = 3, db=None) -> list[dict]:
    return recall_by_vector(identity, embeddings.embed_queries([query])[0], kinds, k, db)


def list_scoped(identity: Identity, *, kind: Optional[str] = None, status: Optional[str] = None, db=None) -> list[dict]:
    """The memory page: what this caller may see, including superseded and forgotten ones for a manager."""
    db = db if db is not None else get_db()
    query: dict = {"scope.team": identity.team, "visibility_roles": identity.role, "$or": [{"scope.user_id": None}, {"scope.user_id": identity.user_id}]}
    if kind:
        query["kind"] = kind
    if status:
        query["status"] = status
    elif identity.role != "manager":
        query["status"] = "active"
    return [serialize(m) for m in db.memories.find(query, NO_VECTOR).sort("created_at", -1)]


def _may_write(identity: Identity, scope: dict, source_type: str, kind: str) -> Optional[str]:
    """Returns the reason a write is out of scope, or None when it is allowed."""
    if scope.get("team") != identity.team:
        return "a memory can only be written for your own team"
    if scope.get("user_id") is None:
        # The agent's own record of a verdict is the one team-scoped write a marketer's run may make.
        if identity.role != "manager" and not (source_type in ("agent", "review_feedback") and kind == "episodic"):
            return "only a manager can write a team instruction or team fact"
    elif scope["user_id"] != identity.user_id:
        return "a personal note can only be written for yourself"
    return None


def needs_step_up(identity: Identity, scope: dict, source_type: str) -> bool:
    """A manager's change to what the whole team's agent knows is confirmed with a password, every time."""
    return scope.get("user_id") is None and source_type not in ("agent", "review_feedback")


def remember(
    identity: Identity, run_id: str, *, kind: str, text: str, scope: dict, ttl_days: Optional[int] = None,
    source_type: str = "user_note", auth_method: str = "jwt", visibility_roles: Optional[list[str]] = None,
    vector: Optional[list[float]] = None, supersedes=None, db=None,
) -> dict:
    db = db if db is not None else get_db()
    params = {"kind": kind, "text": text, "scope": scope, "source_type": source_type}
    reason = _may_write(identity, scope, source_type, kind)
    if reason:
        gate.record_denial(identity, "memory.write", params, run_id, reason, db=db)
        raise gate.Denied(reason.capitalize() + ".")

    def apply() -> dict:
        doc = {
            "kind": kind, "text": text,
            "scope": {"team": scope["team"], "user_id": scope.get("user_id")},
            "visibility_roles": visibility_roles or (["manager", "marketer"] if scope.get("user_id") is None else [identity.role]),
            "embedding": vector or embeddings.embed_documents([text])[0],
            "status": "active", "supersedes": supersedes,
            "expires_at": _now() + timedelta(days=ttl_days) if ttl_days else None,
            "source": {"run_id": run_id, "type": source_type},
            "created_by": identity.user_id, "created_at": _now(), "use_count": 0, "last_used_at": None,
        }
        doc["_id"] = db.memories.insert_one(doc).inserted_id
        if supersedes is not None:
            db.memories.update_one({"_id": supersedes}, {"$set": {"status": "superseded"}})
        return doc

    saved = gate.guarded(
        identity, "memory.write", params, run_id, apply, auth_method=auth_method,
        undo=lambda m: {"type": "memory.revert", "ref": {"new_id": str(m["_id"]), "superseded_id": str(supersedes) if supersedes is not None else None}},
        summarize=lambda m: {"status": "ok", "summary": f"{kind} memory saved for {'the ' + scope['team'] + ' team' if scope.get('user_id') is None else 'one user'}", "ref": {"collection": "memories", "id": str(m["_id"])}},
        db=db,
    )
    return serialize(saved)


def _owned(identity: Identity, memory_id: str, db) -> dict:
    memory = db.memories.find_one({"_id": oid(memory_id)}, NO_VECTOR)
    # A memory outside the caller's team does not exist as far as they are concerned.
    if not memory or (memory.get("scope") or {}).get("team") != identity.team:
        raise NotFound("No such memory")
    return memory


def correct(identity: Identity, run_id: str, memory_id: str, new_text: str, *, auth_method: str = "jwt", db=None) -> dict:
    """Replace a memory with a corrected one. The old one is kept, marked superseded."""
    db = db if db is not None else get_db()
    old = _owned(identity, memory_id, db)
    return remember(
        identity, run_id, kind=old["kind"], text=new_text, scope=old["scope"], source_type=old.get("source", {}).get("type", "user_note"),
        auth_method=auth_method, visibility_roles=old.get("visibility_roles"), supersedes=old["_id"], db=db,
        ttl_days=None if old.get("expires_at") is None else max(1, (old["expires_at"] - _now()).days),
    )


def forget(identity: Identity, run_id: str, memory_id: str, reason: str, *, auth_method: str = "jwt", db=None) -> None:
    """Stop using a memory. It is kept as a tombstone so the ledger still makes sense."""
    db = db if db is not None else get_db()
    memory = _owned(identity, memory_id, db)
    scope = memory["scope"]
    params = {"memory_id": memory_id, "reason": reason, "text": memory["text"]}
    if identity.role != "manager" and scope.get("user_id") != identity.user_id:
        gate.record_denial(identity, "memory.forget", params, run_id, "only a manager can forget a team memory", db=db)
        raise gate.Denied("Only a manager can forget a team memory.")

    gate.guarded(
        identity, "memory.forget", params, run_id,
        lambda: db.memories.update_one({"_id": memory["_id"]}, {"$set": {"status": "forgotten", "forgotten_at": _now(), "forgotten_by": identity.user_id}}),
        auth_method=auth_method,
        undo={"type": "memory.revert", "ref": {"forgotten_id": memory_id, "previous_status": memory.get("status", "active")}},
        summarize=lambda _: {"status": "ok", "summary": "Memory forgotten", "ref": {"collection": "memories", "id": memory_id}},
        db=db,
    )


def revert(ref: dict, db=None) -> str:
    """Undo a memory write or a forget. Used by rollback."""
    db = db if db is not None else get_db()
    if ref.get("forgotten_id"):
        db.memories.update_one({"_id": oid(ref["forgotten_id"])}, {"$set": {"status": ref.get("previous_status", "active")}, "$unset": {"forgotten_at": "", "forgotten_by": ""}})
        return "forgotten memory restored"
    db.memories.update_one({"_id": oid(ref["new_id"])}, {"$set": {"status": "forgotten", "forgotten_at": _now()}})
    if ref.get("superseded_id"):
        db.memories.update_one({"_id": oid(ref["superseded_id"])}, {"$set": {"status": "active"}})
        return "corrected memory removed and the earlier one reactivated"
    return "memory removed"
