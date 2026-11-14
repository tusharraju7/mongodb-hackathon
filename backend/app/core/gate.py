"""The policy gate and the ledger. Every action with a side effect goes through `guarded()`.

Order, for each action:
  1. stop flag     - a run that was asked to stop does not start another step
  2. permission    - the role must hold the action in `policies`; otherwise a deny is recorded
  3. decision      - the allow is written to the ledger BEFORE anything runs
  4. the action
  5. outcome       - what happened, what it rested on, and how to undo it

The ledger is insert-only: this module never updates or deletes an event.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union

from app.core.db import get_db
from app.models import Identity

SECRET_KEYS = {"password", "token", "authorization", "secret"}
MAX_PARAM_CHARS = 300
# A change to policy or memory is recorded in full: the ledger must show exactly what it said before and after.
FULL_TEXT_KEYS = {"before", "after", "reason"}
MAX_FULL_TEXT_CHARS = 8000


class Denied(Exception):
    """The caller's role does not hold the action. Nothing ran."""


class RunStopped(Exception):
    """The run was asked to stop. The step that was about to start did not run."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actor(identity: Identity) -> dict:
    return {"user_id": identity.user_id, "email": identity.email, "role": identity.role, "team": identity.team}


def redact(params: Optional[dict]) -> dict:
    """What is safe to keep on the ledger: no secrets, no raw files, long text shortened."""
    out: dict = {}
    for key, value in (params or {}).items():
        if key.lower() in SECRET_KEYS:
            continue
        if isinstance(value, (bytes, bytearray)):
            out[key] = f"<{len(value)} bytes>"
        elif isinstance(value, str) and key in FULL_TEXT_KEYS:
            out[key] = value[:MAX_FULL_TEXT_CHARS]
        elif isinstance(value, str) and len(value) > MAX_PARAM_CHARS:
            out[key] = value[:MAX_PARAM_CHARS] + "…"
        elif isinstance(value, dict):
            out[key] = redact(value)
        else:
            out[key] = value
    return out


def _event(db, identity: Identity, run_id: str, event: str, action: str, *, thread_id: Optional[str], auth_method: str, **fields) -> Any:
    doc = {
        "ts": _now(),
        "run_id": run_id,
        "thread_id": thread_id,
        "actor": _actor(identity),
        "event": event,
        "action": action,
        "auth": {"method": auth_method},
        **{k: v for k, v in fields.items() if v is not None},
    }
    return db.ledger.insert_one(doc).inserted_id


# ---------------------------------------------------------------- runs


def open_run(identity: Identity, run_id: str, *, intent: Optional[str] = None, thread_id: Optional[str] = None, input_summary: Optional[str] = None, memory_enabled: bool = True, db=None) -> None:
    """Create the run document if it is new. Safe to call again for the same run."""
    db = db if db is not None else get_db()
    db.runs.update_one(
        {"_id": run_id},
        {
            "$setOnInsert": {
                "_id": run_id, "thread_id": thread_id, "actor": _actor(identity), "status": "running",
                "input": (input_summary or "")[:MAX_PARAM_CHARS], "memory_enabled": memory_enabled, "started_at": _now(),
            },
            **({"$set": {"intent": intent}} if intent else {}),
        },
        upsert=True,
    )


def close_run(run_id: str, status: str, *, tokens: Optional[dict] = None, memories_used: Optional[list] = None, db=None) -> None:
    db = db if db is not None else get_db()
    update = {"status": status, "ended_at": _now()}
    if tokens is not None:
        update["tokens"] = tokens
    if memories_used is not None:
        update["memories_used"] = memories_used
    # A run that was stopped or rolled back keeps that status.
    db.runs.update_one({"_id": run_id, "status": {"$nin": ["stopped", "rolled_back"]}}, {"$set": update})


def request_stop(run_id: str, db=None) -> bool:
    """Ask a running run to stop. It takes effect before its next step; a step in flight is not cancelled."""
    db = db if db is not None else get_db()
    return db.runs.update_one({"_id": run_id, "status": "running"}, {"$set": {"status": "stop_requested"}}).modified_count == 1


def permitted(identity: Identity, action: str, db=None) -> bool:
    db = db if db is not None else get_db()
    policy = db.policies.find_one({"_id": identity.role})
    return bool(policy) and action in policy.get("actions", [])


def record_denial(identity: Identity, action: str, params: Optional[dict], run_id: str, reason: str, *, auth_method: str = "jwt", thread_id: Optional[str] = None, db=None) -> None:
    """Record a refusal decided outside the role check: a failed step-up, a stale approval, a scope breach."""
    db = db if db is not None else get_db()
    _event(db, identity, run_id, "decision", action, thread_id=thread_id, auth_method=auth_method, params=redact(params), decision="deny", reason=reason)


def record_rollback(identity: Identity, action: str, run_id: str, undone: dict, summary: str, db=None) -> None:
    db = db if db is not None else get_db()
    _event(db, identity, run_id, "rollback", action, thread_id=None, auth_method="jwt", undo=undone, result={"status": "ok", "summary": summary})


# ---------------------------------------------------------------- the gate

Resolvable = Union[None, Any, Callable[[Any], Any]]


def _resolve(value: Resolvable, result: Any) -> Any:
    return value(result) if callable(value) else value


def guarded(
    identity: Identity,
    action: str,
    params: Optional[dict],
    run_id: str,
    fn: Callable[[], Any],
    *,
    undo: Resolvable = None,
    policy_refs: Resolvable = None,
    memories_used: Resolvable = None,
    summarize: Optional[Callable[[Any], dict]] = None,
    auth_method: str = "jwt",
    thread_id: Optional[str] = None,
    tokens: Optional[Callable[[], dict]] = None,
    db=None,
) -> Any:
    """Run `fn` under the gate. `undo`, `policy_refs` and `memories_used` may be values or functions of the result.

    `summarize(result)` returns the outcome's `result` object: {status, summary, confidence?, ref?}.
    """
    db = db if db is not None else get_db()
    safe_params = redact(params)

    run = db.runs.find_one({"_id": run_id}, {"status": 1})
    if run and run.get("status") in ("stop_requested", "stopped"):
        if run["status"] == "stop_requested":
            _event(db, identity, run_id, "stop", action, thread_id=thread_id, auth_method=auth_method, params=safe_params, reason="Stop was requested; this step did not start")
            db.runs.update_one({"_id": run_id}, {"$set": {"status": "stopped", "ended_at": _now()}})
        raise RunStopped(f"The run was stopped before '{action}' started.")

    if not permitted(identity, action, db):
        _event(db, identity, run_id, "decision", action, thread_id=thread_id, auth_method=auth_method, params=safe_params, decision="deny", reason=f"role {identity.role} does not hold {action}")
        raise Denied(f"Your role ({identity.role}) is not permitted to do this ({action}).")

    _event(db, identity, run_id, "decision", action, thread_id=thread_id, auth_method=auth_method, params=safe_params, decision="allow", reason=f"role {identity.role} holds {action}")

    try:
        result = fn()
    except Exception as exc:
        _event(db, identity, run_id, "outcome", action, thread_id=thread_id, auth_method=auth_method, result={"status": "error", "summary": f"{type(exc).__name__}: nothing was changed by this step"})
        raise

    _event(
        db, identity, run_id, "outcome", action, thread_id=thread_id, auth_method=auth_method,
        result=(summarize(result) if summarize else {"status": "ok", "summary": action}),
        policy_refs=_resolve(policy_refs, result),
        memories_used=_resolve(memories_used, result),
        undo=_resolve(undo, result),
        tokens=tokens() if tokens else None,
    )
    return result
