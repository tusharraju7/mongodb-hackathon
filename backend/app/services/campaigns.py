"""The ad library: versions, scoped search, approval bound to versions, and the gated release."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core import embeddings, gate
from app.core.db import get_db, oid
from app.models import ComplianceReport, Identity
from app.services import fundamentals, offers

NO_VECTOR = {"embedding": 0}
VISIBLE_TO_SALES = ["released"]
VISIBLE_TO_TEAM = ["pending_review", "approved", "released", "rejected"]


class NotFound(Exception):
    pass


class StaleApproval(Exception):
    """The approval no longer matches what would be released."""

    def __init__(self, changes: list[str]):
        super().__init__("Approval is stale: " + "; ".join(changes))
        self.changes = changes


class NotApprovable(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def visible_statuses(identity: Identity) -> list[str]:
    return VISIBLE_TO_SALES if identity.role == "sales" else VISIBLE_TO_TEAM


def search_document(description: str, summary: str) -> str:
    """The text that is embedded for an ad. The seed script must embed exactly this."""
    return f"{description} {summary}".strip()


def card(c: dict) -> dict:
    assets = c.get("assets") or []
    compliance = c.get("compliance") or {}
    return {
        "id": str(c["_id"]), "name": c.get("name"), "team": c.get("team"), "product": c.get("product"),
        "offer_id": c.get("offer_id"), "region": c.get("region"), "channel": c.get("channel"), "language": c.get("language"),
        "version": c.get("version", 1), "status": c.get("status"), "modality": c.get("modality", "text"), "text": c.get("text"),
        "asset": {"type": assets[0]["type"], "url": f"/assets/{assets[0]['file_id']}"} if assets else None,
        "summary": c.get("summary"), "facts": c.get("facts"), "source": c.get("source"), "derived_from": c.get("derived_from"),
        "compliance_verdict": compliance.get("verdict"), "confidence_band": (compliance.get("confidence") or {}).get("band"),
        "route": compliance.get("route"), "approved": bool(c.get("approval")), "created_at": c.get("created_at"),
    }


def full(c: dict) -> dict:
    out = {k: v for k, v in c.items() if k != "embedding"}
    out["id"] = str(out.pop("_id"))
    return out


def _load(identity: Identity, campaign_id: str, db) -> dict:
    c = db.campaigns.find_one({"_id": oid(campaign_id)}, NO_VECTOR)
    # An ad of another team, or one this role may not see, does not exist as far as the caller is concerned.
    if not c or c.get("team") != identity.team or c.get("status") not in visible_statuses(identity):
        raise NotFound("No such ad")
    return c


def get(identity: Identity, campaign_id: str, db=None) -> dict:
    return _load(identity, campaign_id, db if db is not None else get_db())


def list_for(identity: Identity, *, status: Optional[str] = None, db=None) -> list[dict]:
    db = db if db is not None else get_db()
    allowed = visible_statuses(identity)
    statuses = [status] if status in allowed else ([] if status else allowed)
    return [card(c) for c in db.campaigns.find({"team": identity.team, "status": {"$in": statuses}}, NO_VECTOR).sort("created_at", -1)]


def search_by_vector(identity: Identity, vector: list[float], k: int = 1, db=None) -> list[dict]:
    """The closest ads this caller may see. Team and status are filters inside the search."""
    db = db if db is not None else get_db()
    pipeline = [
        {"$vectorSearch": {
            "index": "campaigns_vec", "path": "embedding", "queryVector": vector, "numCandidates": 60, "limit": k,
            "filter": {"team": identity.team, "status": {"$in": visible_statuses(identity)}},
        }},
        {"$set": {"_score": {"$meta": "vectorSearchScore"}}},
        {"$project": NO_VECTOR},
    ]
    hits = list(db.campaigns.aggregate(pipeline))
    gate.emit("retrieval", "campaign.search", params={"collection": "campaigns", "filter": {"team": identity.team, "status": visible_statuses(identity)}, "limit": k},
              result={"status": "ok", "summary": f"{len(hits)} ad(s) in scope", "hits": [{"id": str(h["_id"]), "score": round(h.get("_score", 0), 4)} for h in hits]})
    return hits


def search(identity: Identity, query: str, *, k: int = 1, db=None) -> list[dict]:
    return [card(c) for c in search_by_vector(identity, embeddings.embed_queries([query])[0], k, db)]


def submit(
    identity: Identity, run_id: str, *, name: Optional[str], text: str, ctx: dict, facts: dict, summary: str, description: str,
    modality: str, file_id: Optional[str], mime: Optional[str], compliance: ComplianceReport, cache_key: Optional[str] = None,
    campaign_id: Optional[str] = None, source: str = "submitted", derived_from: Optional[int] = None,
    vector: Optional[list[float]] = None, step_key: Optional[str] = None, db=None,
) -> dict:
    """File an ad, or the next version of one. A new version always clears the approval.

    With a `step_key` the filing is checkpointed: a run that is resumed does not file twice.
    """
    db = db if db is not None else get_db()
    existing = _load(identity, campaign_id, db) if campaign_id else None
    params = {"name": name or (existing or {}).get("name"), "modality": modality, "offer_id": ctx.get("offer_id"), "campaign_id": campaign_id, "source": source}

    def apply() -> dict:
        report = {**compliance.model_dump(), "checked_at": _now(), "cache_key": cache_key}
        assets = [{"type": modality, "file_id": file_id, "mime": mime}] if file_id and modality in ("audio", "image", "video") else []
        fields = {
            "text": text, "visual_notes": ctx.get("visual_notes"), "summary": summary, "description": description, "facts": facts,
            "assets": assets, "modality": modality, "language": ctx.get("language") or facts.get("language") or "en",
            "source": source, "derived_from": derived_from, "status": "pending_review", "compliance": report,
            "embedding": vector or embeddings.embed_documents([search_document(description, summary)])[0],
            "run_id": run_id, "updated_at": _now(),
        }
        if existing:
            previous = {k: existing.get(k) for k in ("version", "text", "assets", "modality", "source", "derived_from", "status", "summary")}
            previous["compliance"] = {k: (existing.get("compliance") or {}).get(k) for k in ("verdict", "route", "confidence")}
            previous["archived_at"] = _now()
            db.campaigns.update_one(
                {"_id": existing["_id"]},
                {"$set": {**fields, "version": existing.get("version", 1) + 1}, "$unset": {"approval": "", "released_at": ""}, "$push": {"history": previous}},
            )
            return db.campaigns.find_one({"_id": existing["_id"]}, NO_VECTOR)
        doc = {
            **fields, "team": identity.team, "name": name or "Untitled ad", "product": ctx.get("product"),
            "offer_id": ctx.get("offer_id"), "region": ctx.get("region"), "channel": ctx.get("channel", "unspecified"),
            "budget": ctx.get("budget"), "version": 1, "history": [], "created_by": identity.user_id, "created_at": _now(),
        }
        doc["_id"] = db.campaigns.insert_one(doc).inserted_id
        doc.pop("embedding", None)
        return doc

    def adopt() -> Optional[dict]:
        # Every version carries the run that filed it, so an interrupted run can find its own filing.
        query = {"run_id": run_id, "team": identity.team, **({"_id": existing["_id"]} if existing else {})}
        return db.campaigns.find_one(query, NO_VECTOR)

    return gate.guarded(
        identity, "campaign.submit", params, run_id, apply,
        undo=lambda c: {"type": "campaign.rollback", "ref": {"id": str(c["_id"]), "version": c.get("version", 1)}},
        summarize=lambda c: {"status": "ok", "summary": f"Filed version {c.get('version', 1)} of '{c.get('name')}' as pending review", "ref": {"collection": "campaigns", "id": str(c["_id"])}},
        facts={"target_team": (existing or {}).get("team", identity.team)}, step_key=step_key, adopt=adopt, db=db,
    )


def approve(identity: Identity, run_id: str, campaign_id: str, feedback: Optional[str] = None, db=None) -> dict:
    """Approve the current version. The approval records exactly what was reviewed."""
    db = db if db is not None else get_db()
    c = _load(identity, campaign_id, db)
    report = c.get("compliance") or {}
    params = {"campaign_id": campaign_id, "ad_version": c.get("version", 1), "feedback": feedback}
    if not gate.permitted(identity, "campaign.approve", db):
        gate.guarded(identity, "campaign.approve", params, run_id, lambda: None, db=db)  # records the denial and raises
    if c.get("status") != "pending_review" or report.get("verdict") != "pass":
        why = "only an ad that is pending review and has passed its review can be approved"
        gate.record_denial(identity, "campaign.approve", params, run_id, why, db=db)
        raise NotApprovable(why.capitalize() + ". Regenerate a compliant version first.")

    offer = offers.get(c.get("offer_id"), db) or {}

    def apply() -> dict:
        approval = {
            "by": identity.user_id, "at": _now(), "ad_version": c.get("version", 1),
            "policy_versions": report.get("checked_fundamentals", []), "offer_version": offer.get("version"),
            "memories": report.get("memories_used", []), "run_id": run_id,
        }
        db.campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "approved", "approval": approval, "review_feedback": feedback}})
        return db.campaigns.find_one({"_id": c["_id"]}, NO_VECTOR)

    return gate.guarded(
        identity, "campaign.approve", params, run_id, apply,
        facts={"target_team": c.get("team"), "ad_status": c.get("status"), "verdict": report.get("verdict")},
        policy_refs=report.get("checked_fundamentals", []),
        undo={"type": "campaign.status", "ref": {"id": campaign_id, "status": "pending_review", "clear_approval": True}},
        summarize=lambda d: {"status": "ok", "summary": f"Approved version {d.get('version', 1)} of '{d.get('name')}'", "ref": {"collection": "campaigns", "id": campaign_id}},
        db=db,
    )


def reject(identity: Identity, run_id: str, campaign_id: str, feedback: str, db=None) -> dict:
    db = db if db is not None else get_db()
    c = _load(identity, campaign_id, db)

    def apply() -> dict:
        db.campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "rejected", "review_feedback": feedback, "rejected_by": identity.user_id}, "$unset": {"approval": ""}})
        return db.campaigns.find_one({"_id": c["_id"]}, NO_VECTOR)

    return gate.guarded(
        identity, "campaign.approve", {"campaign_id": campaign_id, "decision": "reject", "feedback": feedback}, run_id, apply,
        undo={"type": "campaign.status", "ref": {"id": campaign_id, "status": c.get("status")}},
        summarize=lambda d: {"status": "ok", "summary": f"Rejected '{d.get('name')}'", "ref": {"collection": "campaigns", "id": campaign_id}},
        db=db,
    )


def stale_changes(campaign: dict, current_versions: dict[str, Optional[int]], offer: Optional[dict], offer_valid: bool) -> list[str]:
    """Pure check: what has changed since this ad was approved. An empty list means the approval holds."""
    approval = campaign.get("approval")
    if campaign.get("status") != "approved" or not approval:
        return ["the ad is not approved"]
    changes = []
    if approval.get("ad_version") != campaign.get("version", 1):
        changes.append(f"the ad changed from version {approval.get('ad_version')} to {campaign.get('version', 1)} after approval")
    for ref in approval.get("policy_versions", []):
        now = current_versions.get(ref["key"])
        if now is None:
            changes.append(f"{ref['key']} is no longer in effect")
        elif now != ref["version"]:
            changes.append(f"{ref['key']} changed from version {ref['version']} to {now}")
    if not campaign.get("offer_id"):
        return changes  # this ad has no offer record to compare
    if offer is None:
        changes.append(f"offer {campaign.get('offer_id')} no longer exists")
    else:
        if approval.get("offer_version") is not None and offer.get("version") != approval["offer_version"]:
            changes.append(f"offer {offer['_id']} changed from version {approval['offer_version']} to {offer.get('version')}")
        if not offer_valid:
            changes.append(f"offer {offer['_id']} is outside its validity dates")
    return changes


def release(identity: Identity, run_id: str, campaign_id: str, db=None) -> dict:
    """Release an approved ad, but only if the approval still matches the ad, the policies and the offer."""
    db = db if db is not None else get_db()
    c = _load(identity, campaign_id, db)
    params = {"campaign_id": campaign_id, "ad_version": c.get("version", 1)}
    if not gate.permitted(identity, "campaign.release", db):
        gate.guarded(identity, "campaign.release", params, run_id, lambda: None, db=db)  # records the denial and raises

    offer = offers.get(c.get("offer_id"), db)
    keys = [r["key"] for r in (c.get("approval") or {}).get("policy_versions", [])]
    changes = stale_changes(c, fundamentals.current_versions(keys, db), offer, bool(offer) and offers.is_valid(offer))
    if changes:
        gate.record_denial(identity, "campaign.release", {**params, "changes": changes}, run_id, "approval is stale: " + "; ".join(changes), db=db)
        if c.get("status") == "approved":
            db.campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "pending_review"}, "$unset": {"approval": ""}})
        raise StaleApproval(changes)

    def apply() -> dict:
        db.campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "released", "released_at": _now(), "released_by": identity.user_id}})
        return db.campaigns.find_one({"_id": c["_id"]}, NO_VECTOR)

    return gate.guarded(
        identity, "campaign.release", params, run_id, apply,
        facts={"target_team": c.get("team"), "ad_status": c.get("status"), "stale_changes": changes},
        policy_refs=c["approval"].get("policy_versions", []),
        undo={"type": "campaign.status", "ref": {"id": campaign_id, "status": "approved"}},
        summarize=lambda d: {"status": "ok", "summary": f"Released version {d.get('version', 1)} of '{d.get('name')}'", "ref": {"collection": "campaigns", "id": campaign_id}},
        db=db,
    )


def rollback(ref: dict, db=None) -> str:
    """Undo a filing or a status change. Used by run rollback. Files of a removed version are deleted."""
    from app.services import media

    db = db if db is not None else get_db()
    c = db.campaigns.find_one({"_id": oid(ref["id"])}, NO_VECTOR)
    if not c:
        return "ad not found"
    if "status" in ref and "version" not in ref:
        update: dict = {"$set": {"status": ref["status"]}}
        if ref.get("clear_approval"):
            update["$unset"] = {"approval": ""}
        if ref["status"] != "released":
            update.setdefault("$unset", {})["released_at"] = ""
        db.campaigns.update_one({"_id": c["_id"]}, update)
        return f"ad returned to {ref['status']}"
    if c.get("version", 1) != ref.get("version"):
        return "a later version exists; nothing undone"
    for asset in c.get("assets") or []:
        if c.get("source") == "regenerated":
            media.delete(asset["file_id"], db)
    history = c.get("history") or []
    if not history:
        db.campaigns.update_one({"_id": c["_id"]}, {"$set": {"status": "rolled_back"}, "$unset": {"approval": ""}})
        return "ad marked rolled back"
    previous = history[-1]
    restored = {k: previous.get(k) for k in ("version", "text", "assets", "modality", "source", "derived_from", "summary", "compliance")}
    restored["status"] = "pending_review"
    db.campaigns.update_one({"_id": c["_id"]}, {"$set": restored, "$pop": {"history": 1}, "$unset": {"approval": ""}})
    return f"version {c.get('version')} removed; version {previous.get('version')} is current again"


def restore_report(ref: dict, db=None) -> str:
    """Undo a re-review that updated an ad's report in place. Used by run rollback."""
    db = db if db is not None else get_db()
    c = db.campaigns.find_one({"_id": oid(ref["id"])}, NO_VECTOR)
    if not c or c.get("version", 1) != ref.get("version"):
        return "a later version exists; nothing undone"
    update: dict = {"$set": {"compliance": ref.get("compliance"), "status": ref.get("status")}}
    if ref.get("approval"):
        update["$set"]["approval"] = ref["approval"]
    db.campaigns.update_one({"_id": c["_id"]}, update)
    return "earlier review restored"
