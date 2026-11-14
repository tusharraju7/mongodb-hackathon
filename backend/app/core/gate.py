"""The policy gate, the ledger and the step journal. Every action with a side effect goes through `guarded()`.

For each step, in this order:
  1. stop flag      a run that was asked to stop does not start another step
  2. checkpoint     a step this run already completed is not done again; its stored result is returned
  3. authorize      five checks, the first failure decides: identity, role, initiator, scope and state, limits
  4. decision       the allow or deny is written to the ledger BEFORE anything runs
  5. the action
  6. outcome        what happened, what it rested on, and how to undo it; the result is checkpointed

What an agent may do is decided by data in Atlas (`policies` for roles, `action_rules` for the rest)
and by this file. A model never sees those rules and cannot change them.

The ledger is insert-only and chained: every event carries the hash of the one before it in its run,
so an edited or removed event is detectable (`verify_chain`).
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Union

from pymongo.errors import DuplicateKeyError

from app.core.db import get_db, oid
from app.models import Identity

SECRET_KEYS = {"password", "token", "authorization", "secret"}
MAX_PARAM_CHARS = 300
# A change to policy or memory is recorded in full: the ledger must show exactly what it said before and after.
FULL_TEXT_KEYS = {"before", "after", "reason"}
MAX_FULL_TEXT_CHARS = 8000
GENESIS = "0" * 64
RUN_STALE_SECONDS = int(os.environ.get("RUN_STALE_SECONDS", "120"))
DEFAULT_LIMITS = {"steps": 60, "model_calls": 20, "tokens": 200000, "external_calls": 8}
RESUMABLE = ("interrupted", "error")
# Only these appear in the default audit view; the rest are detail (`/audit?detail=true`).
CORE_EVENTS = ["decision", "outcome", "stop", "rollback", "checkpoint", "crash_detected", "resume", "tool_call"]

# The rule for each action beyond "which roles hold it". These are the defaults; a document in
# `action_rules` with the same _id replaces the default for that action, so the rules can be read
# and changed in Atlas without a deploy. An action with no rule may be taken by the agent.
HUMAN = ["human"]
DEFAULT_RULES: dict[str, dict] = {
    "compliance.check": {"initiators": ["human", "agent"], "preconditions": ["same_team"], "note": "Review an ad. Reads only; the verdict is computed in code."},
    "campaign.submit": {"initiators": ["human", "agent"], "preconditions": ["same_team"], "note": "File an ad or its next version as pending review. Never approves."},
    "asset.regenerate": {"initiators": ["human", "agent"], "preconditions": ["same_team"], "note": "Produce a corrected version. Rendered only after the copy has passed review."},
    "campaign.search": {"initiators": ["human", "agent"], "note": "Search the library inside the caller's team and visible statuses."},
    "campaign.ask": {"initiators": ["human", "agent"], "note": "Answer a question about an ad the caller may see."},
    "memory.write": {"initiators": ["human", "agent"], "preconditions": ["same_team"], "step_up": "team scope", "note": "The agent may only record its own past verdicts. A team instruction is written by a manager, with their password."},
    "memory.read": {"initiators": ["human", "agent"]},
    "fundamentals.read": {"initiators": ["human", "agent"]},
    "campaign.approve": {"initiators": HUMAN, "preconditions": ["same_team", "pending_review", "passed_review"], "note": "A manager's deliberate click. The agent can never approve."},
    "campaign.release": {"initiators": HUMAN, "preconditions": ["same_team", "approved", "approval_current"], "note": "Refused when the ad, a policy or the offer changed after approval."},
    "fundamentals.update": {"initiators": HUMAN, "step_up": "always", "note": "A policy clause changes only by a manager, with their password, keeping the old version."},
    "fundamentals.review": {"initiators": HUMAN},
    "memory.forget": {"initiators": HUMAN, "preconditions": ["same_team"], "step_up": "team scope"},
    "run.stop": {"initiators": HUMAN},
    "run.rollback": {"initiators": HUMAN},
    "audit.read": {"initiators": HUMAN},
    "agent.run": {"initiators": ["human", "agent"], "note": "One turn of the agent loop: the model reads the results so far and picks its next tool. Each tool it picks is authorised on its own."},
    "user.access": {"initiators": HUMAN, "preconditions": ["same_team"], "step_up": "always", "note": "Disable or re-enable a team member. Takes effect at the next step of anything they have running."},
}


class Denied(Exception):
    """The step was refused. Nothing ran. `check` names which of the five checks decided."""

    def __init__(self, message: str, check: str = "role"):
        super().__init__(message)
        self.check = check


class RunStopped(Exception):
    """The run was asked to stop. The step that was about to start did not run."""


class SimulatedCrash(Exception):
    """Raised by fault injection right after a step completes. The run is left exactly as a crash would leave it."""


def _now() -> datetime:
    # MongoDB keeps milliseconds. Truncating here means what is hashed is what is stored.
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


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


def digest(value: Any) -> str:
    """A short fingerprint of any content, for the ledger to point at without copying it."""
    return hashlib.sha256(_canonical(value).encode()).hexdigest()[:24]


# ---------------------------------------------------------------- the ledger: ordered, chained events


def _plain(value: Any) -> Any:
    """A form of the value that is identical before it is stored and after it is read back."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(event: dict) -> str:
    body = {k: v for k, v in event.items() if k not in ("_id", "hash")}
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


_append_lock = threading.Lock()
# Per database client: run id -> (last seq, last hash), so appending needs no read.
_head_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _heads_of(db) -> dict:
    return _head_cache.setdefault(db.client, {})


def _head(db, run_id: str) -> tuple[int, str]:
    heads, key = _heads_of(db), (db.name, run_id)
    if key not in heads:
        last = db.ledger.find_one({"run_id": run_id, "seq": {"$exists": True}}, {"seq": 1, "hash": 1}, sort=[("seq", -1)])
        heads[key] = (last["seq"], last["hash"]) if last else (-1, GENESIS)
    return heads[key]


def _event(db, identity: Identity, run_id: str, event: str, action: str, *, thread_id: Optional[str], auth_method: str, **fields) -> Any:
    body = {
        "ts": _now(),
        "run_id": run_id,
        "thread_id": thread_id,
        "actor": _actor(identity),
        "event": event,
        "action": action,
        "auth": {"method": auth_method},
        **{k: v for k, v in fields.items() if v is not None},
    }
    with _append_lock:  # one writer at a time in this process
        heads, key = _heads_of(db), (db.name, run_id)
        if len(heads) > 5000:
            heads.clear()
        for _ in range(6):
            seq, prev_hash = _head(db, run_id)
            doc = {**body, "seq": seq + 1, "prev_hash": prev_hash}
            doc["hash"] = event_hash(doc)
            try:
                inserted = db.ledger.insert_one(doc).inserted_id
            except DuplicateKeyError:
                # Another process appended to this run first (a stop, or crash recovery). Take its
                # event as the one before ours and try again, so the chain never forks.
                heads.pop(key, None)
                continue
            heads[key] = (doc["seq"], doc["hash"])
            return inserted
    raise RuntimeError(f"Could not append to the ledger of run {run_id}")


def verify_chain(run_id: str, db=None) -> dict:
    """Recompute the run's hash chain. Reports whether it is intact and, if not, the first event that is wrong."""
    db = db if db is not None else get_db()
    events = list(db.ledger.find({"run_id": run_id}).sort([("seq", 1), ("_id", 1)]))
    chained = [e for e in events if "hash" in e]
    if not chained:
        return {"run_id": run_id, "events": len(events), "chained": 0, "intact": None, "note": "This run's events were recorded before chaining, or were seeded."}
    prev, expected_seq = GENESIS, chained[0]["seq"]
    for e in chained:
        problem = None
        if e["seq"] != expected_seq:
            problem = f"an event is missing before sequence {e['seq']}"
        elif e.get("prev_hash") != prev:
            problem = "its link to the previous event does not match"
        elif event_hash(e) != e["hash"]:
            problem = "its content was changed after it was written"
        if problem:
            return {"run_id": run_id, "events": len(events), "chained": len(chained), "intact": False, "first_bad_seq": e["seq"], "problem": problem}
        prev, expected_seq = e["hash"], e["seq"] + 1
    return {"run_id": run_id, "events": len(events), "chained": len(chained), "intact": True, "head": prev}


# ---------------------------------------------------------------- who and what is acting right now


@dataclass
class _Context:
    identity: Identity
    run_id: str
    thread_id: Optional[str] = None
    span_id: Optional[str] = None
    db: Any = None
    auth_method: str = "jwt"


_current: contextvars.ContextVar[Optional[_Context]] = contextvars.ContextVar("gate_context", default=None)
_step_prefix: contextvars.ContextVar[str] = contextvars.ContextVar("gate_step_prefix", default="")


class step_scope:
    """Namespaces step keys, so a lane run twice in one run (an agent reviewing the original and
    then the corrected ad) checkpoints each pass separately instead of reusing the first."""

    def __init__(self, prefix: str):
        self.prefix = prefix

    def __enter__(self):
        self._token = _step_prefix.set(_step_prefix.get() + self.prefix)
        return self

    def __exit__(self, *exc):
        _step_prefix.reset(self._token)


def _key(step_key: Optional[str]) -> Optional[str]:
    return _step_prefix.get() + step_key if step_key else step_key
_initiator: contextvars.ContextVar[str] = contextvars.ContextVar("gate_initiator", default="human")


class acting_as:
    """Marks what follows as initiated by the agent, or by a person's direct request (the default).

    Some actions may only ever be taken at a person's direct request; see `action_rules`.
    """

    def __init__(self, initiator: str):
        self.initiator = initiator

    def __enter__(self):
        self._token = _initiator.set(self.initiator)
        return self

    def __exit__(self, *exc):
        _initiator.reset(self._token)


class fresh_request:
    """Every HTTP request starts as a person's direct request, outside any step, whatever was going on
    in the code that made the call."""

    def __enter__(self):
        self._tokens = (_initiator.set("human"), _current.set(None))
        return self

    def __exit__(self, *exc):
        _initiator.reset(self._tokens[0])
        _current.reset(self._tokens[1])


def emit(event: str, action: str, **fields) -> None:
    """Record a detail of the step now running: a model call, a retrieval, a finding, a conflict.

    Does nothing outside a gated step, so the services can call it freely.
    """
    ctx = _current.get()
    if ctx is None:
        return
    _event(ctx.db, ctx.identity, ctx.run_id, event, action, thread_id=ctx.thread_id, auth_method=ctx.auth_method, parent_span_id=ctx.span_id, **fields)


def record(identity: Identity, run_id: str, event: str, action: str, *, thread_id: Optional[str] = None, db=None, **fields) -> None:
    """Add a detail event to a run from outside a step, for example one event per finding after a review."""
    _event(db if db is not None else get_db(), identity, run_id, event, action, thread_id=thread_id, auth_method="jwt", **fields)


class detail_context:
    """Lets `emit` and `count` work for a call made outside a gated step (the router's intent call)."""

    def __init__(self, identity: Identity, run_id: str, thread_id: Optional[str] = None, db=None):
        self.ctx = _Context(identity, run_id, thread_id, None, db if db is not None else get_db())

    def __enter__(self):
        self._token = _current.set(self.ctx)
        return self

    def __exit__(self, *exc):
        _current.reset(self._token)


def count(model_calls: int = 0, tokens: int = 0, external_calls: int = 0) -> None:
    """Add to the running run's usage, which the limits check reads."""
    ctx = _current.get()
    if ctx is None:
        return
    inc = {k: v for k, v in {"usage.model_calls": model_calls, "usage.tokens": tokens, "usage.external_calls": external_calls}.items() if v}
    if inc:
        ctx.db.runs.update_one({"_id": ctx.run_id}, {"$inc": inc})


# ---------------------------------------------------------------- runs


def open_run(
    identity: Identity, run_id: str, *, intent: Optional[str] = None, thread_id: Optional[str] = None, input_summary: Optional[str] = None,
    memory_enabled: bool = True, request: Optional[dict] = None, crash_after: Optional[str] = None, db=None,
) -> None:
    """Create the run document if it is new. Safe to call again for the same run.

    `request` is what is needed to resume the run after a crash. It never holds a password.
    """
    db = db if db is not None else get_db()
    on_insert = {
        "_id": run_id, "thread_id": thread_id, "actor": _actor(identity), "status": "running", "attempt": 1,
        "input": (input_summary or "")[:MAX_PARAM_CHARS], "memory_enabled": memory_enabled, "started_at": _now(),
        "steps": {}, "usage": {"steps": 0, "model_calls": 0, "tokens": 0, "external_calls": 0},
    }
    if request is not None:
        on_insert["request"] = request
    setting: dict = {"heartbeat_at": _now()}
    if intent:
        setting["intent"] = intent
    if crash_after and os.environ.get("ALLOW_FAULT_INJECTION", "").lower() == "true":
        setting["crash_after"] = crash_after
    db.runs.update_one({"_id": run_id}, {"$setOnInsert": on_insert, "$set": setting}, upsert=True)


def close_run(run_id: str, status: str, *, tokens: Optional[dict] = None, memories_used: Optional[list] = None, db=None) -> None:
    db = db if db is not None else get_db()
    update = {"status": status, "ended_at": _now()}
    if tokens is not None:
        update["tokens"] = tokens
    if memories_used is not None:
        update["memories_used"] = memories_used
    # A run that was stopped or rolled back keeps that status.
    db.runs.update_one({"_id": run_id, "status": {"$nin": ["stopped", "rolled_back"]}}, {"$set": update, "$unset": {"crash_after": ""}})


def request_stop(run_id: str, db=None) -> bool:
    """Ask a running run to stop. It takes effect before its next step; a step in flight is not cancelled."""
    db = db if db is not None else get_db()
    return db.runs.update_one({"_id": run_id, "status": "running"}, {"$set": {"status": "stop_requested"}}).modified_count == 1


def sweep_interrupted(stale_seconds: Optional[int] = None, run_id: Optional[str] = None, scope: Optional[dict] = None, db=None) -> list[str]:
    """Find runs that stopped without finishing (a crash) and mark them interrupted.

    A run is taken to have crashed when it is still marked running and has not reported a step for
    `stale_seconds`. The last completed step is recorded, so it can be resumed from there.
    """
    db = db if db is not None else get_db()
    stale = RUN_STALE_SECONDS if stale_seconds is None else stale_seconds
    query: dict = {**(scope or {}), "status": "running", "heartbeat_at": {"$lte": _now() - timedelta(seconds=stale)}}
    if run_id:
        query["_id"] = run_id
    found = []
    for run in db.runs.find(query):
        steps = run.get("steps") or {}
        done = [k for k, v in steps.items() if v.get("status") == "done"]
        in_doubt = [k for k, v in steps.items() if v.get("status") == "started"]
        changed = db.runs.update_one({"_id": run["_id"], "status": "running"}, {"$set": {"status": "interrupted", "interrupted_at": _now()}, "$unset": {"crash_after": ""}})
        if not changed.modified_count:
            continue
        actor = Identity(**{**run["actor"], "name": ""})
        _event(
            db, actor, run["_id"], "crash_detected", "run.recover", thread_id=run.get("thread_id"), auth_method="jwt",
            result={"status": "error", "summary": f"The run stopped without finishing. Completed: {', '.join(done) or 'nothing'}. In doubt: {', '.join(in_doubt) or 'nothing'}."},
            params={"completed_steps": done, "in_doubt_steps": in_doubt, "detected_by": "recovery sweep", "silent_for_seconds": stale},
        )
        found.append(run["_id"])
    return found


def begin_resume(identity: Identity, run_id: str, db=None) -> dict:
    """Put an interrupted run back into the running state for its owner. Returns the run."""
    db = db if db is not None else get_db()
    sweep_interrupted(run_id=run_id, db=db)
    run = db.runs.find_one({"_id": run_id})
    if not run or run["actor"]["user_id"] != identity.user_id:
        raise Denied("Only the person who started a run can resume it.", "scope")
    if run["status"] not in RESUMABLE:
        raise Denied(f"This run is {run['status']}, so there is nothing to resume.", "state")
    if not run.get("request"):
        raise Denied("This run did not record what is needed to resume it.", "state")
    db.runs.update_one({"_id": run_id}, {"$set": {"status": "running", "heartbeat_at": _now()}, "$inc": {"attempt": 1}, "$unset": {"ended_at": "", "crash_after": ""}})
    done = [k for k, v in (run.get("steps") or {}).items() if v.get("status") == "done"]
    _event(db, identity, run_id, "resume", "run.resume", thread_id=run.get("thread_id"), auth_method="jwt", params={"attempt": run.get("attempt", 1) + 1, "completed_steps": done},
           result={"status": "ok", "summary": f"Resuming after {len(done)} completed step(s)"})
    return run


# ---------------------------------------------------------------- deciding what may be done


def permitted(identity: Identity, action: str, db=None) -> bool:
    """The role check alone. `authorize()` is the full decision."""
    db = db if db is not None else get_db()
    policy = db.policies.find_one({"_id": identity.role})
    return bool(policy) and action in policy.get("actions", [])


def action_rule(action: str, db) -> tuple[dict, dict]:
    """The rule for an action and the per-run limits: the stored ones where they exist, else the defaults."""
    stored = {d["_id"]: d for d in db.action_rules.find({"_id": {"$in": [action, "_limits"]}})}
    rule = stored.get(action) or DEFAULT_RULES.get(action) or {}
    return rule, {**DEFAULT_LIMITS, **((stored.get("_limits") or {}).get("per_run") or {})}


def all_rules(db=None) -> dict:
    """Every action, who holds it, and its rule: what `GET /policies/actions` shows."""
    db = db if db is not None else get_db()
    stored = {d["_id"]: d for d in db.action_rules.find({})}
    roles: dict[str, list[str]] = {}
    for policy in db.policies.find({}):
        for action in policy.get("actions", []):
            roles.setdefault(action, []).append(policy["_id"])
    out = []
    for action in sorted(set(roles) | set(DEFAULT_RULES)):
        rule = {k: v for k, v in (stored.get(action) or DEFAULT_RULES.get(action) or {}).items() if k != "_id"}
        out.append({"action": action, "roles": sorted(roles.get(action, [])), "initiators": rule.get("initiators", ["human", "agent"]),
                    "preconditions": rule.get("preconditions", []), "step_up": rule.get("step_up"), "note": rule.get("note"),
                    "source": "action_rules" if action in stored else "default"})
    limits = {**DEFAULT_LIMITS, **((stored.get("_limits") or {}).get("per_run") or {})}
    return {"actions": out, "limits_per_run": limits, "checks": ["identity", "role", "initiator", "state", "limits"]}


# Named conditions on the target of an action. Each returns the reason it fails, or None.
PRECONDITIONS: dict[str, Callable[[Identity, dict], Optional[str]]] = {
    "same_team": lambda i, f: None if f.get("target_team") in (None, i.team) else "the target belongs to another team",
    "pending_review": lambda i, f: None if f.get("ad_status") == "pending_review" else f"the ad is {f.get('ad_status')}, not pending review",
    "passed_review": lambda i, f: None if f.get("verdict") == "pass" else "the ad has not passed its review",
    "approved": lambda i, f: None if f.get("ad_status") == "approved" else f"the ad is {f.get('ad_status')}, not approved",
    "approval_current": lambda i, f: None if not f.get("stale_changes") else "approval is stale: " + "; ".join(f["stale_changes"]),
}


FACT_FOR = {"same_team": "target_team", "pending_review": "ad_status", "passed_review": "verdict", "approved": "ad_status", "approval_current": "stale_changes"}


@dataclass
class Decision:
    allow: bool
    decided_by: str            # identity | role | initiator | state | limits | all
    reason: str
    checks: list[dict] = field(default_factory=list)


def authorize(identity: Identity, action: str, *, run_id: Optional[str] = None, facts: Optional[dict] = None, initiator: Optional[str] = None, usage: Optional[dict] = None, user: Optional[dict] = None, db=None) -> Decision:
    """Decide whether this step may run. Five checks in order; the first that fails decides.

      identity   still an active user, with the role and team their token says
      role       the role holds the action
      initiator  the agent may take this action, or it is a person's direct request
      state      the target is in the user's team and in a state that allows the action
      limits     the run is within its budget
    """
    db = db if db is not None else get_db()
    initiator = initiator or _initiator.get()
    facts = facts or {}
    checks: list[dict] = []

    def fail(name: str, reason: str) -> Decision:
        checks.append({"check": name, "ok": False})
        return Decision(False, name, reason, checks)

    user = user or current_user(identity, db)
    if not user:
        return fail("identity", "this user no longer exists")
    if user.get("status", "active") != "active":
        return fail("identity", f"this user is {user.get('status')}")
    if user.get("role") != identity.role or user.get("team") != identity.team:
        return fail("identity", "this user's role or team has changed since they signed in")
    if int(user.get("auth_version", 0)) != int(identity.auth_version):
        return fail("identity", "this user's access was changed since they signed in")
    checks.append({"check": "identity", "ok": True})

    if not permitted(identity, action, db):
        return fail("role", f"role {identity.role} does not hold {action}")
    checks.append({"check": "role", "ok": True})

    rule, limits = action_rule(action, db)
    if initiator not in rule.get("initiators", ["human", "agent"]):
        return fail("initiator", f"{action} may only be done at a person's direct request, not by the agent")
    checks.append({"check": "initiator", "ok": True})

    for name in rule.get("preconditions", []):
        # A condition is checked when the caller has supplied the fact it rests on.
        if name in PRECONDITIONS and FACT_FOR[name] in facts:
            reason = PRECONDITIONS[name](identity, facts)
            if reason:
                return fail("state", reason)
    checks.append({"check": "state", "ok": True})

    if usage is None and run_id:
        usage = (db.runs.find_one({"_id": run_id}, {"usage": 1}) or {}).get("usage")
    for key, cap in limits.items():
        if (usage or {}).get(key, 0) >= cap:
            return fail("limits", f"this run has reached its limit of {cap} {key.replace('_', ' ')}")
    checks.append({"check": "limits", "ok": True})
    return Decision(True, "all", f"role {identity.role} holds {action}", checks)


def current_user(identity: Identity, db) -> Optional[dict]:
    """The user as they are in the database right now, not as their token remembers them."""
    return db.users.find_one({"_id": oid(identity.user_id)}, {"password_hash": 0}) or db.users.find_one({"email": identity.email}, {"password_hash": 0})


def record_denial(identity: Identity, action: str, params: Optional[dict], run_id: str, reason: str, *, auth_method: str = "jwt", thread_id: Optional[str] = None, db=None) -> None:
    """Record a refusal decided outside `authorize`: a failed step-up, a scope breach found by a service."""
    db = db if db is not None else get_db()
    _event(db, identity, run_id, "decision", action, thread_id=thread_id, auth_method=auth_method, params=redact(params), decision="deny", reason=reason, initiator=_initiator.get())


def record_rollback(identity: Identity, action: str, run_id: str, undone: dict, summary: str, db=None) -> None:
    db = db if db is not None else get_db()
    _event(db, identity, run_id, "rollback", action, thread_id=None, auth_method="jwt", undo=undone, result={"status": "ok", "summary": summary})


def preflight(identity: Identity, run_id: str, actions: list[str], *, thread_id: Optional[str] = None, db=None) -> list[dict]:
    """Before a lane starts: check every step it intends to take, and record the plan on the run.

    If any step would be refused, the refusal goes on the ledger and nothing runs. Each step is
    still checked again when it executes, because the user's standing and the target's state can
    change in between.
    """
    db = db if db is not None else get_db()
    user = current_user(identity, db)
    usage = (db.runs.find_one({"_id": run_id}, {"usage": 1}) or {}).get("usage") or {}
    decisions = [(a, authorize(identity, a, usage=usage, user=user, db=db) if user else authorize(identity, a, usage=usage, db=db)) for a in dict.fromkeys(actions)]
    plan = [{"action": a, "allow": d.allow, "decided_by": d.decided_by, "initiator": _initiator.get()} for a, d in decisions]
    db.runs.update_one({"_id": run_id}, {"$set": {"plan": plan}})
    refused = next(((a, d) for a, d in decisions if not d.allow), None)
    if refused:
        action, decision = refused
        _event(db, identity, run_id, "decision", action, thread_id=thread_id, auth_method="jwt", params={"planned_steps": [p["action"] for p in plan]},
               decision="deny", reason=decision.reason, decided_by=decision.decided_by, checks=decision.checks, initiator=_initiator.get())
        raise Denied(_denial_text(identity, action, decision), decision.decided_by)
    return plan


def step_result(run_id: str, step_key: str, db=None) -> Any:
    """The stored result of a step this run has completed, or None. For steps that only compute."""
    db = db if db is not None else get_db()
    step_key = _key(step_key)
    run = db.runs.find_one({"_id": run_id}, {f"steps.{step_key}": 1})
    step = ((run or {}).get("steps") or {}).get(step_key) or {}
    return step.get("result") if step.get("status") == "done" else None


def steps_done(run_id: str, db=None) -> set[str]:
    db = db if db is not None else get_db()
    run = db.runs.find_one({"_id": run_id}, {"steps": 1}) or {}
    prefix = _step_prefix.get()
    return {k[len(prefix):] for k, v in (run.get("steps") or {}).items() if v.get("status") == "done" and k.startswith(prefix)}


def save_step(run_id: str, step_key: str, result: Any, db=None) -> None:
    _checkpoint(db if db is not None else get_db(), run_id, _key(step_key), result, None)


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
    facts: Optional[dict] = None,
    step_key: Optional[str] = None,
    dump: Optional[Callable[[Any], Any]] = None,
    load: Optional[Callable[[Any], Any]] = None,
    adopt: Optional[Callable[[], Any]] = None,
    db=None,
) -> Any:
    """Run `fn` under the gate. `undo`, `policy_refs` and `memories_used` may be values or functions of the result.

    `summarize(result)` returns the outcome's `result` object: {status, summary, confidence?, ref?}.
    `facts` describe the target (its team, status and so on) for the state check.

    With a `step_key` the step is checkpointed in the run's journal:
      - if this run already completed it, the stored result is returned and nothing runs;
      - if it was started but never finished, `adopt()` looks for the effect it may have had and, if
        found, takes that as the result, so nothing is done twice;
      - otherwise it runs, and its result is stored (`dump` and `load` convert it to and from storage).
    """
    db = db if db is not None else get_db()
    step_key = _key(step_key)
    safe_params = redact(params)
    span_id = uuid.uuid4().hex[:16]
    base = {"thread_id": thread_id, "auth_method": auth_method}

    run = db.runs.find_one({"_id": run_id}, {"status": 1, "crash_after": 1, "usage": 1, **({f"steps.{step_key}": 1} if step_key else {})})
    if run and run.get("status") in ("stop_requested", "stopped"):
        if run["status"] == "stop_requested":
            _event(db, identity, run_id, "stop", action, **base, params=safe_params, reason="Stop was requested; this step did not start")
            db.runs.update_one({"_id": run_id}, {"$set": {"status": "stopped", "ended_at": _now()}})
        raise RunStopped(f"The run was stopped before '{action}' started.")
    if run and run.get("status") in ("interrupted", "rolled_back"):
        # A run that was given up on (taken for dead, or undone) takes no further step, even if the
        # process that was running it turns out to be alive. It can be resumed from its checkpoints.
        raise RunStopped(f"The run is {run['status'].replace('_', ' ')}; '{action}' did not start.")

    # The journal: do not repeat what this run has already done.
    journal = ((run or {}).get("steps") or {}).get(step_key) if step_key else None
    if journal and journal.get("status") == "done":
        _event(db, identity, run_id, "checkpoint", action, **base, span_id=span_id, params={"step": step_key}, result={"status": "ok", "summary": f"'{step_key}' was already done in this run; its result was reused"})
        return load(journal["result"]) if load else journal.get("result")

    decision = authorize(identity, action, facts=facts, usage=(run or {}).get("usage") or {}, db=db)
    if not decision.allow:
        _event(db, identity, run_id, "decision", action, **base, span_id=span_id, params=safe_params, decision="deny", reason=decision.reason,
               decided_by=decision.decided_by, checks=decision.checks, initiator=_initiator.get())
        raise Denied(_denial_text(identity, action, decision), decision.decided_by)

    if journal and journal.get("status") == "started" and adopt is not None:
        found = adopt()
        if found is not None:
            _checkpoint(db, run_id, step_key, found, dump)
            _event(db, identity, run_id, "checkpoint", action, **base, span_id=span_id, params={"step": step_key},
                   result={"status": "ok", "summary": f"'{step_key}' had taken effect before the run was interrupted; that effect was kept, not repeated"})
            return found

    _event(db, identity, run_id, "decision", action, **base, span_id=span_id, params=safe_params, decision="allow", reason=decision.reason,
           decided_by=decision.decided_by, checks=decision.checks, initiator=_initiator.get(), step=step_key)
    if run is not None:
        update: dict = {"$set": {"heartbeat_at": _now()}, "$inc": {"usage.steps": 1}}
        if step_key:
            update["$set"][f"steps.{step_key}"] = {"status": "started", "at": _now(), "action": action}
        db.runs.update_one({"_id": run_id}, update)

    started = time.time()
    token = _current.set(_Context(identity, run_id, thread_id, span_id, db, auth_method))
    try:
        result = fn()
    except Exception as exc:
        _current.reset(token)
        _event(db, identity, run_id, "outcome", action, **base, span_id=span_id, duration_ms=int((time.time() - started) * 1000),
               result={"status": "error", "summary": f"{type(exc).__name__}: nothing was changed by this step"})
        raise
    _current.reset(token)

    _event(
        db, identity, run_id, "outcome", action, **base, span_id=span_id, duration_ms=int((time.time() - started) * 1000),
        result=(summarize(result) if summarize else {"status": "ok", "summary": action}),
        policy_refs=_resolve(policy_refs, result),
        memories_used=_resolve(memories_used, result),
        undo=_resolve(undo, result),
        tokens=tokens() if tokens else None,
        step=step_key,
    )
    if step_key and run is not None:
        _checkpoint(db, run_id, step_key, result, dump)
        if run.get("crash_after") == step_key:
            raise SimulatedCrash(f"Fault injection: the run was abandoned right after '{step_key}'.")
    return result


def _checkpoint(db, run_id: str, step_key: str, result: Any, dump: Optional[Callable[[Any], Any]]) -> None:
    stored = dump(result) if dump else result
    db.runs.update_one({"_id": run_id}, {"$set": {f"steps.{step_key}": {"status": "done", "at": _now(), "result": stored}, "heartbeat_at": _now()}})


def _denial_text(identity: Identity, action: str, decision: Decision) -> str:
    if decision.decided_by == "role":
        return f"Your role ({identity.role}) is not permitted to do this ({action})."
    if decision.decided_by == "identity":
        return f"This cannot continue: {decision.reason}. Please sign in again."
    return f"This cannot be done: {decision.reason}."
