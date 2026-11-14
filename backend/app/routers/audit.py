from __future__ import annotations

import json
import time
from typing import Iterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core import gate, security
from app.core.db import get_db
from app.models import Identity

router = APIRouter(tags=["audit"])

STREAM_SECONDS = 300
TERMINAL = {"completed", "blocked", "needs_input", "denied", "stopped", "rolled_back", "error"}


def _json(event: dict) -> dict:
    out = json.loads(json.dumps(event, default=str))
    out["id"] = out.pop("_id", None)
    return out


def _scope(identity: Identity) -> dict:
    """A manager reads their team's ledger. Anyone else reads only their own actions."""
    if identity.role == "manager":
        return {"actor.team": identity.team}
    return {"actor.user_id": identity.user_id}


def _require(identity: Identity) -> None:
    if not gate.permitted(identity, "audit.read"):
        gate.guarded(identity, "audit.read", {}, "audit-read", lambda: None)  # records the denial and raises


@router.get("/audit")
def audit(run_id: Optional[str] = None, actor: Optional[str] = None, action: Optional[str] = None, limit: int = 200, identity: Identity = Depends(security.current_identity)) -> list[dict]:
    """Ledger events, oldest first within a run, newest first otherwise."""
    _require(identity)
    query = _scope(identity)
    if run_id:
        query["run_id"] = run_id
    if actor and identity.role == "manager":
        query["$or"] = [{"actor.user_id": actor}, {"actor.email": actor}]
    if action:
        query["action"] = action
    cursor = get_db().ledger.find(query).sort([("ts", 1 if run_id else -1), ("_id", 1 if run_id else -1)]).limit(min(max(limit, 1), 1000))
    return [_json(e) for e in cursor]


def _events(run_id: str, scope: dict) -> Iterator[str]:
    """Replay what the run has already logged, then follow the ledger's change stream until the run ends."""
    db = get_db()
    seen = set()
    deadline = time.time() + STREAM_SECONDS

    def emit(event: dict) -> Optional[str]:
        if event["_id"] in seen:
            return None
        seen.add(event["_id"])
        return f"data: {json.dumps(_json(event))}\n\n"

    match = {"operationType": "insert", "fullDocument.run_id": run_id, **{f"fullDocument.{k}": v for k, v in scope.items()}}
    with db.ledger.watch([{"$match": match}], max_await_time_ms=1000) as stream:
        for event in db.ledger.find({"run_id": run_id, **scope}).sort("_id", 1):
            line = emit(event)
            if line:
                yield line
        idle_after_end = 0
        while time.time() < deadline:
            change = stream.try_next()
            if change is not None:
                line = emit(change["fullDocument"])
                if line:
                    yield line
                continue
            run = db.runs.find_one({"_id": run_id}, {"status": 1})
            if run and run.get("status") in TERMINAL:
                idle_after_end += 1
                if idle_after_end >= 2:  # one more quiet second after the run ended
                    yield f"event: end\ndata: {json.dumps({'status': run['status']})}\n\n"
                    return
            else:
                yield ": keep-alive\n\n"


@router.get("/audit/stream")
def audit_stream(run_id: str, identity: Identity = Depends(security.current_identity)) -> StreamingResponse:
    """Server-sent events for one run. The token may be passed as `?token=` because EventSource cannot set headers."""
    _require(identity)
    return StreamingResponse(_events(run_id, _scope(identity)), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
