from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core import gate, security
from app.core.db import get_db
from app.models import Identity
from app.services import campaigns, fundamentals, memory

router = APIRouter(tags=["runs"])


def _load(identity: Identity, run_id: str) -> dict:
    run = get_db().runs.find_one({"_id": run_id})
    actor = (run or {}).get("actor") or {}
    mine = actor.get("user_id") == identity.user_id
    same_team_manager = identity.role == "manager" and actor.get("team") == identity.team
    if not run or not (mine or same_team_manager):
        raise HTTPException(status_code=404, detail="No such run")
    return run


def _json(run: dict) -> dict:
    out = json.loads(json.dumps(run, default=str))
    out["id"] = out.pop("_id")
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    return _json(_load(identity, run_id))


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Ask a run to stop. It halts before its next step; a call already in flight is not cancelled."""
    _load(identity, run_id)
    requested = gate.guarded(
        identity, "run.stop", {"target_run": run_id}, f"ctl-{uuid.uuid4()}", lambda: gate.request_stop(run_id),
        summarize=lambda ok: {"status": "ok", "summary": "Stop requested" if ok else "The run had already finished; nothing to stop"},
    )
    return {**_json(_load(identity, run_id)), "stop_requested": requested}


def _undo(descriptor: dict, actor: Identity, db) -> str:
    kind, ref = descriptor.get("type"), descriptor.get("ref") or {}
    if kind == "fundamental.restore":
        fundamentals.restore(ref["key"], ref["version"], actor, db)
        return f"{ref['key']} restored to version {ref['version']}"
    if kind == "memory.revert":
        return memory.revert(ref, db)
    if kind in ("campaign.rollback", "campaign.status"):
        return campaigns.rollback(ref, db)
    return f"nothing to undo for {kind}"


@router.post("/runs/{run_id}/rollback")
def rollback_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Undo what a run changed in our own records, newest first. External calls are not undone."""
    run = _load(identity, run_id)
    db = get_db()

    def apply() -> list[str]:
        if run.get("status") == "rolled_back":
            return []
        done = []
        outcomes = db.ledger.find({"run_id": run_id, "event": "outcome", "undo": {"$exists": True}}).sort("_id", -1)
        for event in outcomes:
            summary = _undo(event["undo"], identity, db)
            gate.record_rollback(identity, event["action"], run_id, event["undo"], summary, db=db)
            done.append(summary)
        db.runs.update_one({"_id": run_id}, {"$set": {"status": "rolled_back"}})
        return done

    undone = gate.guarded(
        identity, "run.rollback", {"target_run": run_id}, f"ctl-{uuid.uuid4()}", apply,
        summarize=lambda d: {"status": "ok", "summary": f"Rolled back {len(d)} change(s)" if d else "Nothing to roll back"},
    )
    return {**_json(_load(identity, run_id)), "undone": undone}
