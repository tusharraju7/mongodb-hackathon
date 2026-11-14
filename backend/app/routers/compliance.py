from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.agent import lanes
from app.core import gate, llm, security
from app.models import Identity

router = APIRouter(tags=["compliance"])


class CheckBody(BaseModel):
    text: Optional[str] = None
    file_id: Optional[str] = None
    campaign_id: Optional[str] = None
    name: Optional[str] = None
    product: str = "credit_card"
    offer_id: Optional[str] = None
    region: str = "CA"
    channel: str = "email"
    language: Optional[str] = None
    budget: Optional[dict] = None
    save: bool = False
    use_memory: bool = True
    run_id: Optional[str] = None


CTX_KEYS = ("name", "product", "offer_id", "region", "channel", "language", "budget", "campaign_id")


def execute(identity: Identity, run_id: str, request: dict) -> dict:
    """Review an ad. Also what a resumed run calls, with the request it stored."""
    usage = llm.TokenUsage()
    ctx = {k: request.get(k) for k in CTX_KEYS}
    try:
        out = lanes.review_lane(identity, run_id, text=request.get("text"), file_id=request.get("file_id"), ctx=ctx, use_memory=request.get("use_memory", True), usage=usage, save=request.get("save", False))
    except gate.SimulatedCrash:
        raise
    except gate.Denied:
        gate.close_run(run_id, "denied")
        raise
    except Exception:
        gate.close_run(run_id, "error", tokens=usage.as_dict())
        raise
    gate.close_run(run_id, out["status"], tokens=usage.as_dict(), memories_used=[m["id"] for m in out["memories_used"]])
    report = next((c["data"] for c in out["cards"] if c["type"] == "compliance_report"), None)
    campaign = next((c["data"] for c in out["cards"] if c["type"] == "campaign"), None)
    return {**(report or {}), "run_id": run_id, "campaign": campaign, "memory_chips": out["memories_used"], "tokens": usage.as_dict()}


@router.post("/compliance/check")
def check(body: CheckBody, identity: Identity = Depends(security.current_identity), x_crash_after: Optional[str] = Header(None)) -> dict:
    """Review an ad directly, without the chat. Returns the report; with `save` it is also filed in the library."""
    run_id = body.run_id or str(uuid.uuid4())
    request = {"kind": "check", **body.model_dump(exclude={"run_id"})}
    gate.open_run(identity, run_id, intent="review", input_summary=body.text or body.campaign_id or body.file_id, memory_enabled=body.use_memory, request=request, crash_after=x_crash_after)
    return execute(identity, run_id, request)
