from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core import gate, security
from app.models import Identity
from app.services import fundamentals

router = APIRouter(tags=["policies"])


class UpdateBody(BaseModel):
    text: str
    reason: str
    password: Optional[str] = None  # asked for on every change; compared and discarded
    rule: Optional[dict] = None
    summary: Optional[str] = None
    run_id: Optional[str] = None


def _require(identity: Identity, action: str) -> None:
    if not gate.permitted(identity, action):
        gate.guarded(identity, action, {}, f"read-{uuid.uuid4()}", lambda: None)  # records the denial and raises


@router.get("/fundamentals")
def list_clauses(identity: Identity = Depends(security.current_identity)) -> list[dict]:
    _require(identity, "fundamentals.read")
    return fundamentals.list_all(identity)


@router.get("/fundamentals/{fundamental_id}/history")
def clause_history(fundamental_id: str, identity: Identity = Depends(security.current_identity)) -> list[dict]:
    _require(identity, "fundamentals.read")
    return fundamentals.history(fundamental_id)


@router.put("/fundamentals/{fundamental_id}")
def update_clause(fundamental_id: str, body: UpdateBody, identity: Identity = Depends(security.current_identity)) -> dict:
    """Change a policy clause. Manager only, password every time, old version kept, before and after on the ledger."""
    run_id = body.run_id or str(uuid.uuid4())
    gate.open_run(identity, run_id, intent="memory_update", input_summary=f"edit {fundamental_id}: {body.reason}")
    try:
        clause = fundamentals.update(identity, run_id, fundamental_id, text=body.text, reason=body.reason, password=body.password, rule=body.rule, summary=body.summary)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**clause, "run_id": run_id}
