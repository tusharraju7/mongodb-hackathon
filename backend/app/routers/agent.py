from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agent import agent_loop
from app.core import gate, llm, security
from app.models import Identity

router = APIRouter(tags=["agent"])


class AgentBody(BaseModel):
    goal: str
    campaign_id: Optional[str] = None
    run_id: Optional[str] = None
    max_turns: int = agent_loop.MAX_TURNS


@router.post("/agent")
def agent(body: AgentBody, identity: Identity = Depends(security.current_identity)) -> dict:
    """Give the agent a goal. It chooses its own steps; the gate authorises each one.

    Returns the reply, the steps it took (including any it was refused), the ad and review it ended
    on, and the run id for `/runs/{id}/trace`, `/audit?run_id=` and `/runs/{id}/rollback`.
    """
    run_id = body.run_id or str(uuid.uuid4())
    usage = llm.TokenUsage()
    gate.open_run(identity, run_id, intent="agent", input_summary=body.goal)
    try:
        out = agent_loop.run_agent(identity, run_id, body.goal, campaign_id=body.campaign_id, max_turns=body.max_turns, usage=usage)
    except gate.SimulatedCrash:
        raise
    except Exception:
        gate.close_run(run_id, "error", tokens=usage.as_dict())
        raise
    gate.close_run(run_id, out["status"], tokens=usage.as_dict())
    return {**out, "run_id": run_id, "tokens": usage.as_dict()}
