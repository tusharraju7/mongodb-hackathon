"""Runs: follow one, stop it, resume it after a crash, roll it back, and test what caused its verdict."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core import gate, llm, security
from app.core.db import get_db
from app.models import Identity
from app.services import attribution, campaigns, fundamentals, media, memory

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
    """The run for the web app. Step results can be large, so only each step's state is returned."""
    out = json.loads(json.dumps({k: v for k, v in run.items() if k not in ("steps", "request")}, default=str))
    out["id"] = out.pop("_id")
    out["steps"] = {k: {"status": v.get("status"), "at": str(v.get("at")), "action": v.get("action")} for k, v in (run.get("steps") or {}).items()}
    out["resumable"] = run.get("status") in gate.RESUMABLE and bool(run.get("request"))
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    gate.sweep_interrupted(run_id=run_id)  # a run that died is noticed when someone looks at it
    return _json(_load(identity, run_id))


@router.post("/runs/recover")
def recover(identity: Identity = Depends(security.current_identity)) -> dict:
    """Find runs that stopped without finishing and mark them interrupted, so they can be resumed or rolled back."""
    scope = {"actor.team": identity.team} if identity.role == "manager" else {"actor.user_id": identity.user_id}
    found = gate.sweep_interrupted(scope=scope)
    db = get_db()
    waiting = [_json(r) for r in db.runs.find({**scope, "status": {"$in": list(gate.RESUMABLE)}, "request": {"$exists": True}}).sort("started_at", -1).limit(20)]
    return {"newly_interrupted": found, "resumable": waiting}


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Ask a run to stop. It halts before its next step; a call already in flight is not cancelled."""
    _load(identity, run_id)
    requested = gate.guarded(
        identity, "run.stop", {"target_run": run_id}, f"ctl-{uuid.uuid4()}", lambda: gate.request_stop(run_id),
        summarize=lambda ok: {"status": "ok", "summary": "Stop requested" if ok else "The run had already finished; nothing to stop"},
    )
    return {**_json(_load(identity, run_id)), "stop_requested": requested}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Continue an interrupted run from its last completed step.

    Only the person who started it can resume it, and every remaining step is authorised again, so
    a user who has lost the right since the crash cannot finish the run. Completed steps are not
    repeated: their stored results are reused, and no model is called for them again.
    """
    from app.routers import campaigns as campaigns_router
    from app.routers import chat, compliance

    run = gate.begin_resume(identity, run_id)
    request = run["request"]
    execute = {"chat": chat.execute, "check": compliance.execute, "regenerate": campaigns_router.execute_regenerate}[request["kind"]]
    return {**execute(identity, run_id, request), "resumed": True, "attempt": run.get("attempt", 1) + 1}


def _undo(descriptor: dict, actor: Identity, db) -> str:
    kind, ref = descriptor.get("type"), descriptor.get("ref") or {}
    if kind == "fundamental.restore":
        fundamentals.restore(ref["key"], ref["version"], actor, db)
        return f"{ref['key']} restored to version {ref['version']}"
    if kind == "memory.revert":
        return memory.revert(ref, db)
    if kind == "memory.strength":
        return memory.restore_strength(ref, db)
    if kind == "memory.uncontest":
        return memory.uncontest(ref, db)
    if kind == "user.access":
        from app.core.db import oid

        db.users.update_one({"_id": oid(ref["id"])}, {"$set": {"status": ref["status"]}, "$inc": {"auth_version": 1}})
        return f"user returned to {ref['status']}"
    if kind == "campaign.report":
        return campaigns.restore_report(ref, db)
    if kind in ("campaign.rollback", "campaign.status"):
        return campaigns.rollback(ref, db)
    return f"nothing to undo for {kind}"


def _clean_in_doubt(run_id: str, handled: set[str], identity: Identity, db) -> list[str]:
    """What a crashed step may have left behind without recording it: found by the run id each artefact carries."""
    done = []
    for c in db.campaigns.find({"run_id": run_id, "status": {"$ne": "rolled_back"}}, {"embedding": 0}):
        if str(c["_id"]) not in handled:
            ref = {"id": str(c["_id"]), "version": c.get("version", 1)}
            summary = "unrecorded filing: " + campaigns.rollback(ref, db)
            gate.record_rollback(identity, "campaign.submit", run_id, {"type": "campaign.rollback", "ref": ref}, summary, db=db)
            done.append(summary)
    for m in db.memories.find({"source.run_id": run_id, "status": "active"}, {"embedding": 0}):
        if str(m["_id"]) not in handled:
            ref = {"new_id": str(m["_id"]), "superseded_id": str(m["supersedes"]) if m.get("supersedes") is not None else None}
            summary = "unrecorded memory: " + memory.revert(ref, db)
            gate.record_rollback(identity, "memory.write", run_id, {"type": "memory.revert", "ref": ref}, summary, db=db)
            done.append(summary)
    orphans = 0
    for f in media.run_files(run_id, db=db):
        file_id = str(f["_id"])
        in_use = db.campaigns.count_documents({"status": {"$ne": "rolled_back"}, "$or": [{"assets.file_id": file_id}, {"history.assets.file_id": file_id}, {"compliance.annotated_url": f"/assets/{file_id}"}]}, limit=1)
        if not in_use:
            media.delete(file_id, db)
            orphans += 1
    if orphans:
        summary = f"{orphans} file(s) made by this run removed"
        gate.record_rollback(identity, "asset.regenerate", run_id, {"type": "files.delete", "ref": {"count": orphans}}, summary, db=db)
        done.append(summary)
    return done


@router.post("/runs/{run_id}/rollback")
def rollback_run(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Undo what a run changed in our own records, newest first. External calls are not undone.

    For a run that crashed, this also removes what a half-finished step left behind.
    """
    gate.sweep_interrupted(run_id=run_id)
    run = _load(identity, run_id)
    db = get_db()

    def apply() -> list[str]:
        if run.get("status") == "rolled_back":
            return []
        done, handled = [], set()
        outcomes = db.ledger.find({"run_id": run_id, "event": "outcome", "undo": {"$exists": True}}).sort("_id", -1)
        for event in outcomes:
            summary = _undo(event["undo"], identity, db)
            gate.record_rollback(identity, event["action"], run_id, event["undo"], summary, db=db)
            ref = event["undo"].get("ref") or {}
            handled |= {str(v) for k, v in ref.items() if k in ("id", "new_id") and v}
            done.append(summary)
        done += _clean_in_doubt(run_id, handled, identity, db)
        db.runs.update_one({"_id": run_id}, {"$set": {"status": "rolled_back"}})
        return done

    undone = gate.guarded(
        identity, "run.rollback", {"target_run": run_id}, f"ctl-{uuid.uuid4()}", apply,
        summarize=lambda d: {"status": "ok", "summary": f"Rolled back {len(d)} change(s)" if d else "Nothing to roll back"},
    )
    return {**_json(_load(identity, run_id)), "undone": undone}


@router.get("/runs/{run_id}/trace")
def trace(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """The whole run, in order: the plan, each step with the checks that allowed it and what happened
    inside it (model calls, retrievals), each finding, and whether the record is intact."""
    run = _load(identity, run_id)
    events = [json.loads(json.dumps(e, default=str)) for e in get_db().ledger.find({"run_id": run_id}).sort([("seq", 1), ("_id", 1)])]
    steps: list[dict] = []
    by_span: dict[str, dict] = {}
    for e in events:
        e["id"] = e.pop("_id")
        span, parent = e.get("span_id"), e.get("parent_span_id")
        if parent and parent in by_span:
            by_span[parent]["inside"].append(e)
        elif span and e["event"] in ("decision", "outcome", "checkpoint"):
            node = by_span.get(span)
            if node is None:
                node = by_span[span] = {"span_id": span, "action": e["action"], "step": e.get("step") or (e.get("params") or {}).get("step"), "inside": []}
                steps.append(node)
            node[e["event"]] = e
            node["step"] = node["step"] or e.get("step")
        else:
            steps.append({"event": e["event"], "action": e["action"], "detail": e})
    return {"run": _json(run), "plan": run.get("plan") or [], "steps": steps, "events": len(events), "chain": gate.verify_chain(run_id)}


@router.post("/runs/{run_id}/attribution")
def attribute(run_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """The lesion test: repeat this run's review with each cited memory removed, and report what changed."""
    run = _load(identity, run_id)
    db = get_db()
    reviewed = ((run.get("steps") or {}).get("review") or {}).get("result")
    test_run = f"lesion-{uuid.uuid4()}"
    gate.open_run(identity, test_run, intent="review", input_summary=f"lesion test of run {run_id}")
    usage = llm.TokenUsage()
    try:
        with gate.acting_as("agent"):
            result = gate.guarded(
                identity, "compliance.check", {"step": "lesion_test", "target_run": run_id}, test_run,
                lambda: attribution.lesion_test(identity, test_run, reviewed, usage=usage, db=db), tokens=usage.as_dict,
                memories_used=lambda r: [t["memory_id"] for t in r["tested"]],
                summarize=lambda r: {"status": "ok", "summary": "; ".join(f"{t['memory_id'][-6:]}: {t['effect']}" for t in r["tested"])},
            )
    except attribution.NothingToTest as nothing:
        gate.close_run(test_run, "needs_input")
        raise HTTPException(status_code=409, detail=str(nothing))
    except Exception:
        gate.close_run(test_run, "error", tokens=usage.as_dict())
        raise
    for t in result["tested"]:
        gate.record(identity, test_run, "attribution", "memory.attribution", db=db,
                    params={"target_run": run_id, "memory_id": t["memory_id"], "effect": t["effect"], "with": t.get("with"), "without": t.get("without")},
                    result={"status": "ok", "summary": t["explanation"]})
    db.runs.update_one({"_id": run_id}, {"$set": {"attribution": {**result, "run_id": test_run}}})
    gate.close_run(test_run, "completed", tokens=usage.as_dict(), memories_used=[t["memory_id"] for t in result["tested"]])
    return {**result, "run_id": test_run, "target_run": run_id, "tokens": usage.as_dict()}
