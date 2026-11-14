from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.agent import lanes
from app.core import gate, llm, security
from app.models import Identity
from app.services import campaigns, memory, offers

router = APIRouter(tags=["library"])


class Feedback(BaseModel):
    feedback: Optional[str] = None
    run_id: Optional[str] = None
    voice: bool = False  # regenerate only: also record the corrected copy with ElevenLabs


def _run(identity: Identity, intent: str, run_id: Optional[str], summary: str) -> str:
    run_id = run_id or str(uuid.uuid4())
    gate.open_run(identity, run_id, intent=intent, input_summary=summary)
    return run_id


def _learn(identity: Identity, run_id: str, ad: dict, *, agreed: bool, feedback: Optional[str]) -> None:
    """A manager's decision on a reviewed ad feeds back into memory.

    Agreement strengthens the memories the review used. An override weakens them, and the
    correction is stored as a memory stronger than a routine one, because an unexpected outcome is
    the one most worth remembering. Never allowed to fail the decision itself.
    """
    used = (ad.get("compliance") or {}).get("memories_used") or []
    try:
        if used:
            why = f"a manager's decision on '{ad.get('name')}' {'agreed with' if agreed else 'overrode'} the review"
            memory.reinforce(identity, run_id, used, agreed=agreed, reason=why)
        if not agreed and (feedback or "").strip():
            text = f"A manager rejected the {identity.team} {ad.get('channel')} ad '{ad.get('name')}' although the review had passed it. Reason given: {feedback.strip()}"
            memory.remember(
                identity, run_id, kind="episodic", text=text, scope={"team": identity.team, "user_id": None}, ttl_days=180,
                source_type="review_feedback", strength=memory.SURPRISE_STRENGTH, extra={"surprise": True},
            )
    except Exception:
        pass


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


def execute_regenerate(identity: Identity, run_id: str, request: dict) -> dict:
    """Regenerate an ad. Also what a resumed run calls, with the request it stored."""
    usage = llm.TokenUsage()
    try:
        out = lanes.regenerate_lane(identity, run_id, campaign_id=request["campaign_id"], usage=usage, voice=request.get("voice", False))
    except gate.SimulatedCrash:
        raise
    except Exception:
        gate.close_run(run_id, "error", tokens=usage.as_dict())
        raise
    gate.close_run(run_id, "completed" if out["status"] == "regenerated" else "blocked", tokens=usage.as_dict())
    return {**out, "run_id": run_id, "tokens": usage.as_dict()}


@router.post("/campaigns/{campaign_id}/regenerate")
def regenerate(campaign_id: str, body: Feedback = Feedback(), identity: Identity = Depends(security.current_identity), x_crash_after: Optional[str] = Header(None)) -> dict:
    run_id = body.run_id or str(uuid.uuid4())
    request = {"kind": "regenerate", "campaign_id": campaign_id, "voice": body.voice}
    gate.open_run(identity, run_id, intent="regenerate", input_summary=campaign_id, request=request, crash_after=x_crash_after)
    return execute_regenerate(identity, run_id, request)


@router.get("/campaigns/{campaign_id}/annotated")
def annotated(campaign_id: str, identity: Identity = Depends(security.current_identity)) -> dict:
    """Where the flaws are on an image ad: the marked-up picture and the boxes, as fractions of width and height."""
    c = campaigns.get(identity, campaign_id)
    report = c.get("compliance") or {}
    return {"id": campaign_id, "version": c.get("version", 1), "annotated_url": report.get("annotated_url"), "highlights": report.get("highlights") or []}


@router.post("/campaigns/{campaign_id}/approve")
def approve(campaign_id: str, body: Feedback = Feedback(), identity: Identity = Depends(security.current_identity)) -> dict:
    run_id = _run(identity, "approve", body.run_id, campaign_id)
    try:
        c = campaigns.approve(identity, run_id, campaign_id, body.feedback)
    except Exception:
        gate.close_run(run_id, "denied")
        raise
    _learn(identity, run_id, c, agreed=True, feedback=body.feedback)
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
    # Rejecting an ad the review had passed is a surprise; rejecting one it had flagged is agreement.
    _learn(identity, run_id, c, agreed=(c.get("compliance") or {}).get("verdict") != "pass", feedback=body.feedback)
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
