"""What may be done, by whom, and why: the rules as data, a dry-run of the decision, and access control."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core import gate, security
from app.core.db import get_db, oid
from app.models import Identity
from app.services import campaigns, fundamentals, offers

router = APIRouter(tags=["governance"])


@router.get("/policies/actions")
def actions(identity: Identity = Depends(security.current_identity)) -> dict:
    """Every action, the roles that hold it, whether the agent may take it, and its conditions and limits."""
    return gate.all_rules()


class AuthorizeBody(BaseModel):
    action: str
    campaign_id: Optional[str] = None
    initiator: str = "human"  # "human" for a button the person would click, "agent" for what the assistant could do


@router.post("/authorize")
def authorize(body: AuthorizeBody, identity: Identity = Depends(security.current_identity)) -> dict:
    """Would this be allowed, and which check decides? Nothing is done and nothing is written.

    The web app uses it to disable a button with the reason; a reviewer uses it to probe the rules.
    The same function decides the real action when it is attempted.
    """
    db = get_db()
    facts: dict = {}
    if body.campaign_id:
        try:
            c = campaigns.get(identity, body.campaign_id, db)
        except campaigns.NotFound:
            return {"action": body.action, "allow": False, "decided_by": "state", "reason": "there is no such ad in your scope", "checks": []}
        facts = {"target_team": c.get("team"), "ad_status": c.get("status"), "verdict": (c.get("compliance") or {}).get("verdict")}
        if body.action == "campaign.release":
            offer = offers.get(c.get("offer_id"), db)
            keys = [r["key"] for r in (c.get("approval") or {}).get("policy_versions", [])]
            facts["stale_changes"] = campaigns.stale_changes(c, fundamentals.current_versions(keys, db), offer, bool(offer) and offers.is_valid(offer)) if c.get("status") == "approved" else []
    decision = gate.authorize(identity, body.action, facts=facts, initiator=body.initiator, db=db)
    return {"action": body.action, "initiator": body.initiator, "allow": decision.allow, "decided_by": decision.decided_by, "reason": decision.reason, "checks": decision.checks}


@router.get("/users")
def team_users(identity: Identity = Depends(security.current_identity)) -> list[dict]:
    """The caller's team, for a manager."""
    if not gate.permitted(identity, "user.access"):
        gate.guarded(identity, "user.access", {}, f"read-{uuid.uuid4()}", lambda: None)  # records the denial and raises
    return [
        {"id": str(u["_id"]), "email": u["email"], "name": u.get("name"), "role": u["role"], "team": u["team"], "status": u.get("status", "active")}
        for u in get_db().users.find({"team": identity.team}, {"password_hash": 0}).sort("email", 1)
    ]


class AccessBody(BaseModel):
    status: str  # "active" | "disabled"
    reason: Optional[str] = None
    password: Optional[str] = None


@router.post("/users/{user_id}/access")
def set_access(user_id: str, body: AccessBody, identity: Identity = Depends(security.current_identity)) -> dict:
    """Disable or re-enable a team member. Takes effect at the very next step of anything they have running,
    and every token they hold stops working."""
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'disabled'")
    db = get_db()
    run_id = f"ctl-{uuid.uuid4()}"
    target = db.users.find_one({"_id": oid(user_id)}) or db.users.find_one({"email": user_id})
    params = {"user": user_id, "status": body.status, "reason": body.reason}
    if not gate.permitted(identity, "user.access"):
        gate.guarded(identity, "user.access", params, run_id, lambda: None)
    if not target or target.get("team") != identity.team:
        raise HTTPException(status_code=404, detail="No such user in your team")
    if str(target["_id"]) == identity.user_id:
        gate.record_denial(identity, "user.access", params, run_id, "a manager cannot change their own access")
        raise gate.Denied("You cannot change your own access.", "state")
    if not security.verify_password(identity, body.password):
        gate.record_denial(identity, "user.access", params, run_id, "step-up password missing or wrong")
        raise security.StepUpFailed("This change needs your password, and the one given was missing or wrong.")
    previous = target.get("status", "active")

    def apply() -> dict:
        # Raising the version makes every token issued before this moment fail the identity check.
        db.users.update_one({"_id": target["_id"]}, {"$set": {"status": body.status}, "$inc": {"auth_version": 1}})
        return db.users.find_one({"_id": target["_id"]}, {"password_hash": 0})

    after = gate.guarded(
        identity, "user.access", {**params, "email": target["email"], "before": previous, "after": body.status}, run_id, apply,
        auth_method="jwt+password", facts={"target_team": target.get("team")},
        undo={"type": "user.access", "ref": {"id": str(target["_id"]), "status": previous}},
        summarize=lambda u: {"status": "ok", "summary": f"{u['email']} is now {u['status']}", "ref": {"collection": "users", "id": str(u["_id"])}},
    )
    return {"id": str(after["_id"]), "email": after["email"], "status": after["status"], "auth_version": after.get("auth_version", 0), "run_id": run_id}
