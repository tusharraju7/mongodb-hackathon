from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
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


@router.post("/compliance/check")
def check(body: CheckBody, identity: Identity = Depends(security.current_identity)) -> dict:
    """Review an ad directly, without the chat. Returns the report; with `save` it is also filed in the library."""
    run_id = body.run_id or str(uuid.uuid4())
    usage = llm.TokenUsage()
    gate.open_run(identity, run_id, intent="review", input_summary=body.text or body.campaign_id or body.file_id, memory_enabled=body.use_memory)
    ctx = body.model_dump(include={"name", "product", "offer_id", "region", "channel", "language", "budget", "campaign_id"})
    try:
        out = lanes.review_lane(identity, run_id, text=body.text, file_id=body.file_id, ctx=ctx, use_memory=body.use_memory, usage=usage, save=body.save)
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
