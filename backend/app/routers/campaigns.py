from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agent import lanes
from app.core import gate, llm, security
from app.models import Identity
from app.services import campaigns, offers

router = APIRouter(tags=["library"])


class Feedback(BaseModel):
    feedback: Optional[str] = None
    run_id: Optional[str] = None


def _run(identity: Identity, intent: str, run_id: Optional[str], summary: str) -> str:
    run_id = run_id or str(uuid.uuid4())
    gate.open_run(identity, run_id, intent=intent, input_summary=summary)
    return run_id


@router.get("/offers")
def list_offers(identity: Identity = Depends(security.current_identity)) -> list[dict]:
    return offers.list_all()


@router.get("/offers/{offer_id}")
def get_offer(offer_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    offer = offers.get(offer_id)
    if not offer:
        raise campaigns.NotFound("No such offer")
    return offers.serialize(offer)


@router.get("/campaigns")
def list_campaigns(status: Optional[str] = None, q: Optional[str] = None, identity: Identity = Depends(security.current_identity)) -> list[dict]:
    """The library. What comes back is limited to the caller's team, and for sales to released ads."""
    if q:
        run_id = _run(identity, "ask", None, q)
        hits = gate.guarded(identity, "campaign.search", {"q": q}, run_id, lambda: campaigns.search(identity, q, k=6), summarize=lambda h: {"status": "ok", "summary": f"{len(h)} ads matched"})
        gate.close_run(run_id, "completed")
        return [h for h in hits if not status or h["status"] == status]
    return campaigns.list_for(identity, status=status)


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    return campaigns.full(campaigns.get(identity, campaign_id))


@router.post("/campaigns/{campaign_id}/regenerate")
def regenerate(campaign_id: str, body: Feedback = Feedback(), identity: Identity = Depends(security.current_identity)) -> dict:
    run_id = _run(identity, "regenerate", body.run_id, campaign_id)
    usage = llm.TokenUsage()
    try:
        out = lanes.regenerate_lane(identity, run_id, campaign_id=campaign_id, usage=usage)
    except Exception:
        gate.close_run(run_id, "error", tokens=usage.as_dict())
        raise
    gate.close_run(run_id, "completed" if out["status"] == "regenerated" else "blocked", tokens=usage.as_dict())
    return {**out, "run_id": run_id, "tokens": usage.as_dict()}


@router.post("/campaigns/{campaign_id}/approve")
def approve(campaign_id: str, body: Feedback = Feedback(), identity: Identity = Depends(security.current_identity)) -> dict:
    run_id = _run(identity, "approve", body.run_id, campaign_id)
    try:
        c = campaigns.approve(identity, run_id, campaign_id, body.feedback)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**campaigns.card(c), "run_id": run_id}


@router.post("/campaigns/{campaign_id}/reject")
def reject(campaign_id: str, body: Feedback, identity: Identity = Depends(security.current_identity)) -> dict:
    run_id = _run(identity, "approve", body.run_id, campaign_id)
    try:
        c = campaigns.reject(identity, run_id, campaign_id, body.feedback or "")
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**campaigns.card(c), "run_id": run_id}


@router.post("/campaigns/{campaign_id}/release")
def release(campaign_id: str, body: Feedback = Feedback(), identity: Identity = Depends(security.current_identity)) -> dict:
    """Release an approved ad. Returns 409 with what changed when the approval is stale."""
    run_id = _run(identity, "release", body.run_id, campaign_id)
    try:
        c = campaigns.release(identity, run_id, campaign_id)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    gate.close_run(run_id, "completed")
    return {**campaigns.card(c), "run_id": run_id}
