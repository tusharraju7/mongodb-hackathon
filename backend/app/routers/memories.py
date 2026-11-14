from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from app.core import gate, security
from app.core.db import get_db, oid
from app.models import Identity
from app.services import memory

router = APIRouter(tags=["memory"])


class CreateBody(BaseModel):
    kind: str = "procedural"
    text: str
    scope: Optional[dict] = None  # {team, user_id}; defaults to the caller's team, or to the caller for a non-manager
    ttl_days: Optional[int] = None
    reason: Optional[str] = None
    password: Optional[str] = None
    run_id: Optional[str] = None


class CorrectBody(BaseModel):
    text: str
    reason: Optional[str] = None
    password: Optional[str] = None
    run_id: Optional[str] = None


class ForgetBody(BaseModel):
    reason: str = "no longer wanted"
    password: Optional[str] = None
    run_id: Optional[str] = None


def _step_up(identity: Identity, scope: dict, source_type: str, password: Optional[str], action: str, params: dict, run_id: str) -> str:
    """Team-wide changes need the password, every time. A failure is recorded as a denial."""
    if not memory.needs_step_up(identity, scope, source_type):
        return "jwt"
    if not gate.permitted(identity, action):
        gate.guarded(identity, action, params, run_id, lambda: None)  # records the denial and raises
    if not security.verify_password(identity, password):
        gate.record_denial(identity, action, params, run_id, "step-up password missing or wrong")
        raise security.StepUpFailed("This change needs your password, and the one given was missing or wrong.")
    return "jwt+password"


def _run(identity: Identity, run_id: Optional[str], summary: str) -> str:
    run_id = run_id or str(uuid.uuid4())
    gate.open_run(identity, run_id, intent="memory_update", input_summary=summary)
    return run_id


@router.get("/memories")
def list_memories(kind: Optional[str] = None, status: Optional[str] = None, identity: Identity = Depends(security.current_identity)) -> list[dict]:
    if not gate.permitted(identity, "memory.read"):
        gate.guarded(identity, "memory.read", {}, f"read-{uuid.uuid4()}", lambda: None)
    return memory.list_scoped(identity, kind=kind, status=status)


@router.post("/memories")
def create_memory(body: CreateBody, identity: Identity = Depends(security.current_identity)) -> dict:
    scope = body.scope or {"team": identity.team, "user_id": None if identity.role == "manager" else identity.user_id}
    source = "manager_instruction" if scope.get("user_id") is None else "user_note"
    run_id = _run(identity, body.run_id, body.text)
    params = {"kind": body.kind, "text": body.text, "scope": scope, "reason": body.reason}
    try:
        method = _step_up(identity, scope, source, body.password, "memory.write", params, run_id)
        saved = memory.remember(identity, run_id, kind=body.kind, text=body.text, scope=scope, ttl_days=body.ttl_days, source_type=source, auth_method=method)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**saved, "run_id": run_id}


@router.patch("/memories/{memory_id}")
def correct_memory(memory_id: str, body: CorrectBody, identity: Identity = Depends(security.current_identity)) -> dict:
    run_id = _run(identity, body.run_id, f"correct {memory_id}")
    try:
        old = memory._owned(identity, memory_id, get_db())
        method = _step_up(identity, old["scope"], old.get("source", {}).get("type", "user_note"), body.password, "memory.write", {"memory_id": memory_id, "after": body.text, "reason": body.reason}, run_id)
        saved = memory.correct(identity, run_id, memory_id, body.text, auth_method=method)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**saved, "run_id": run_id}


@router.delete("/memories/{memory_id}", status_code=204)
def forget_memory(memory_id: str, body: ForgetBody = Body(default=ForgetBody()), identity: Identity = Depends(security.current_identity)) -> Response:
    run_id = _run(identity, body.run_id, f"forget {memory_id}")
    try:
        old = memory._owned(identity, memory_id, get_db())
        # Forgetting a team memory is a team-wide change whoever wrote it, so it always needs the password.
        source = "manager_instruction" if old["scope"].get("user_id") is None else "user_note"
        method = _step_up(identity, old["scope"], source, body.password, "memory.forget", {"memory_id": memory_id, "reason": body.reason}, run_id)
        memory.forget(identity, run_id, memory_id, body.reason, auth_method=method)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return Response(status_code=204, headers={"X-Run-Id": run_id})
