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


ALWAYS_ON_LIMIT = 5
AUTHORITY_ORDER = {"binding": 0, "guidance": 1, "precedent": 2, "background": 3}
# A small preference for sources that carry more weight, so a binding decision is not crowded out
# by several loosely related slides. Starting values.
AUTHORITY_BONUS = {"binding": 0.08, "guidance": 0.04, "precedent": 0.02, "background": 0.0}


def authority_of(memory: dict) -> str:
    return memory.get("authority") or {"episodic": "precedent", "procedural": "binding"}.get(memory.get("kind"), "background")


def source_label(memory: dict) -> str:
    src = memory.get("source") or {}
    if src.get("type") == "slack":
        return f"Slack #{src.get('channel')}" + (f", {', '.join(src['authors'])}" if src.get("authors") else "")
    if src.get("type") == "strategy_deck":
        return src.get("title") or "strategy deck"
    if src.get("type") == "ad_decision":
        return f"decision on ad {src.get('ref')}"
    return {"manager_instruction": "manager instruction", "user_note": "personal note", "agent": "earlier review", "review_feedback": "review feedback"}.get(src.get("type"), "")


def for_review(memory: dict, memory_id: str) -> dict:
    """The fields a review needs from a memory, however it is stored."""
    src = memory.get("source") or {}
    when = src.get("date") or memory.get("created_at")
    return {
        "id": memory_id, "kind": memory["kind"], "text": memory["text"], "authority": authority_of(memory),
        "materiality": memory.get("materiality"), "source_label": source_label(memory),
        "date": when.date().isoformat() if hasattr(when, "date") else (str(when)[:10] if when else None),
    }


def select(scored: list[tuple[dict, float]], budget: int) -> list[dict]:
    """Keep the `budget` most relevant memories, then present them by standing and recency.

    `scored` holds (review-shaped memory, similarity). A memory found by several searches keeps its best score.
    """
    best: dict[str, tuple[dict, float]] = {}
    for memory, score in scored:
        if memory["id"] not in best or score > best[memory["id"]][1]:
            best[memory["id"]] = (memory, score)
    ranked = sorted(best.values(), key=lambda x: -(x[1] + AUTHORITY_BONUS[x[0]["authority"]]))
    from app.core.profile import get_profile

    quotas = get_profile()["memory"].get("quotas")
    if quotas:
        # Each standing gets its own share of the budget, so the most relevant binding decisions are
        # always in view and are never crowded out by a run of loosely related slides.
        taken: dict[str, int] = {}
        chosen = []
        for m, _ in ranked:
            if taken.get(m["authority"], 0) < quotas.get(m["authority"], 0):
                chosen.append(m)
                taken[m["authority"]] = taken.get(m["authority"], 0) + 1
    else:
        chosen = [m for m, _ in ranked[:budget]]
    return sorted(chosen, key=lambda m: (AUTHORITY_ORDER[m["authority"]], -(int((m["date"] or "0000-00-00").replace("-", "")))))


def recall_many(identity: Identity, vectors: list[list[float]], kinds: list[str], per_query: int = 3, budget: int = 3, db=None) -> list[dict]:
    """Search memory once per vector (the whole ad, then each claim) and merge. Scope is enforced in each search."""
    db = db if db is not None else get_db()
    at = _now()
    scored: list[tuple[dict, float]] = []
    for vector in vectors:
        pipeline = [
            {"$vectorSearch": {
                "index": "memories_vec", "path": "embedding", "queryVector": vector, "numCandidates": 100, "limit": per_query * 3,
                "filter": {"status": "active", "scope.team": identity.team, "visibility_roles": identity.role, "kind": {"$in": kinds}},
            }},
            {"$set": {"_score": {"$meta": "vectorSearchScore"}}},
            {"$project": NO_VECTOR},
        ]
        hits = [m for m in db.memories.aggregate(pipeline) if _readable(m, identity, at)][:per_query]
        scored += [(for_review(m, str(m["_id"])), 2 * m["_score"] - 1) for m in hits]
    chosen = select(scored, budget)
    # A manager's standing instruction for the whole team applies to every ad, whatever the ad is
    # about, so it is fetched directly and not left to similarity. This also means it takes effect
    # on the very next review, without waiting for the search index to catch up.
    standing = db.memories.find(
        {"status": "active", "scope.team": identity.team, "scope.user_id": None, "visibility_roles": identity.role, "always": True, "kind": {"$in": kinds}},
        NO_VECTOR,
    ).sort("created_at", -1).limit(ALWAYS_ON_LIMIT)
    have = {m["id"] for m in chosen}
    always = [for_review(m, str(m["_id"])) for m in standing if _readable(m, identity, at) and str(m["_id"]) not in have]
    chosen = always + chosen
    if chosen:
        db.memories.update_many({"_id": {"$in": [oid(m["id"]) for m in chosen]}}, {"$inc": {"use_count": 1}, "$set": {"last_used_at": at}})
    return chosen


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
            # An instruction a manager gives the whole team is in view for every review of that team.
            "always": source_type == "manager_instruction" and scope.get("user_id") is None and kind == "procedural",
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
