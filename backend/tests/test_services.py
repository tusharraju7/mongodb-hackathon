"""Library, memory and policy services on an in-memory database. No network."""
import pytest

from app.core import gate, security
from app.models import ComplianceReport
from app.services import campaigns, fundamentals, memory
from tests.conftest import PASSWORD

CHECKED = [{"key": "credit.intro_rate_disclosure", "version": 3}, {"key": "credit.bonus_conditions", "version": 1}]


def report(verdict="pass") -> ComplianceReport:
    route = "none" if verdict == "pass" else "human_review"
    return ComplianceReport(
        verdict=verdict, route=route, route_reason="test", summary="test",
        confidence={"score": 100, "band": "high", "reasons": []}, checked_fundamentals=CHECKED, offer_version=1,
        corrected_copy=None if verdict == "pass" else "fixed copy",
    )


def file_ad(db, who, verdict="pass", **over):
    ctx = {"product": "credit_card", "offer_id": "TCB-FALL-2026", "region": "CA", "channel": "email", "language": "en"}
    kw = dict(name="Test ad", text="copy v1", ctx=ctx, facts={"claims": []}, summary="s", description="d", modality="text", file_id=None, mime=None, compliance=report(verdict), db=db)
    kw.update(over)
    return campaigns.submit(who, "run-file", **kw)


def deny_events(db, action):
    return list(db.ledger.find({"action": action, "decision": "deny"}))


# ---------------------------------------------------------------- approve and release


def test_review_approve_release_happy_path(db, people):
    ad = file_ad(db, people["marketer"])
    ad_id = str(ad["_id"])
    assert ad["status"] == "pending_review" and ad["version"] == 1

    with pytest.raises(gate.Denied):
        campaigns.approve(people["marketer"], "run-a", ad_id, db=db)
    assert deny_events(db, "campaign.approve")

    approved = campaigns.approve(people["manager"], "run-b", ad_id, db=db)
    assert approved["status"] == "approved"
    assert approved["approval"]["ad_version"] == 1 and approved["approval"]["policy_versions"] == CHECKED and approved["approval"]["offer_version"] == 1

    released = campaigns.release(people["marketer"], "run-c", ad_id, db=db)
    assert released["status"] == "released" and released["released_at"]


def test_an_ad_that_did_not_pass_cannot_be_approved(db, people):
    ad = file_ad(db, people["marketer"], verdict="blocked")
    with pytest.raises(campaigns.NotApprovable):
        campaigns.approve(people["manager"], "run-a", str(ad["_id"]), db=db)
    assert db.campaigns.find_one({"_id": ad["_id"]})["status"] == "pending_review"
    assert "passed its review" in deny_events(db, "campaign.approve")[0]["reason"]


def test_release_is_refused_after_a_policy_edit_and_allowed_again_after_rollback(db, people):
    ad = file_ad(db, people["marketer"])
    ad_id = str(ad["_id"])
    campaigns.approve(people["manager"], "run-a", ad_id, db=db)

    fundamentals.update(people["manager"], "run-edit", "credit.intro_rate_disclosure", text="New wording.", reason="tighten", password=PASSWORD, db=db)
    with pytest.raises(campaigns.StaleApproval) as stale:
        campaigns.release(people["marketer"], "run-b", ad_id, db=db)
    assert stale.value.changes == ["credit.intro_rate_disclosure changed from version 3 to 4"]
    after = db.campaigns.find_one({"_id": ad["_id"]})
    assert after["status"] == "pending_review" and "approval" not in after
    assert "stale" in deny_events(db, "campaign.release")[0]["reason"]

    # Rolling the edit back restores version 3, so an approval bound to version 3 holds again.
    fundamentals.restore("credit.intro_rate_disclosure", 3, people["manager"], db)
    assert fundamentals.current_versions(["credit.intro_rate_disclosure"], db) == {"credit.intro_rate_disclosure": 3}
    campaigns.approve(people["manager"], "run-c", ad_id, db=db)
    assert campaigns.release(people["marketer"], "run-d", ad_id, db=db)["status"] == "released"


def test_a_new_version_clears_the_approval_and_keeps_history(db, people):
    ad = file_ad(db, people["marketer"])
    ad_id = str(ad["_id"])
    campaigns.approve(people["manager"], "run-a", ad_id, db=db)
    v2 = file_ad(db, people["marketer"], text="copy v2", campaign_id=ad_id, source="regenerated", derived_from=1)
    assert (v2["version"], v2["status"], v2["source"], v2["derived_from"]) == (2, "pending_review", "regenerated", 1)
    assert "approval" not in v2 and v2["history"][0]["text"] == "copy v1" and v2["history"][0]["version"] == 1
    with pytest.raises(campaigns.StaleApproval):
        campaigns.release(people["marketer"], "run-b", ad_id, db=db)

    assert "version 1 is current again" in campaigns.rollback({"id": ad_id, "version": 2}, db)
    back = db.campaigns.find_one({"_id": ad["_id"]})
    assert (back["version"], back["text"], back["history"]) == (1, "copy v1", [])


def test_stale_changes_names_everything_that_moved():
    ad = {"status": "approved", "version": 3, "offer_id": "TCB-FALL-2026", "approval": {"ad_version": 2, "policy_versions": [{"key": "a", "version": 1}, {"key": "b", "version": 2}, {"key": "c", "version": 1}], "offer_version": 1}}
    changes = campaigns.stale_changes(ad, {"a": 1, "b": 3, "c": None}, {"_id": "TCB-FALL-2026", "version": 2}, offer_valid=False)
    assert changes == [
        "the ad changed from version 2 to 3 after approval",
        "b changed from version 2 to 3",
        "c is no longer in effect",
        "offer TCB-FALL-2026 changed from version 1 to 2",
        "offer TCB-FALL-2026 is outside its validity dates",
    ]
    assert campaigns.stale_changes({**ad, "version": 2}, {"a": 1, "b": 2, "c": 1}, {"_id": "TCB-FALL-2026", "version": 1}, offer_valid=True) == []
    assert campaigns.stale_changes({"status": "pending_review"}, {}, None, False) == ["the ad is not approved"]


# ---------------------------------------------------------------- who sees which ads


def test_sales_see_only_released_ads_of_their_own_team(db, people):
    pending = file_ad(db, people["marketer"])
    released = file_ad(db, people["marketer"], name="Released ad")
    campaigns.approve(people["manager"], "r1", str(released["_id"]), db=db)
    campaigns.release(people["manager"], "r2", str(released["_id"]), db=db)
    quebec = file_ad(db, people["qc_marketer"], name="Quebec ad")

    assert [c["name"] for c in campaigns.list_for(people["sales"], db=db)] == ["Released ad"]
    assert {c["name"] for c in campaigns.list_for(people["marketer"], db=db)} == {"Test ad", "Released ad"}
    with pytest.raises(campaigns.NotFound):
        campaigns.get(people["sales"], str(pending["_id"]), db)
    with pytest.raises(campaigns.NotFound):
        campaigns.get(people["marketer"], str(quebec["_id"]), db)
    assert campaigns.list_for(people["sales"], status="pending_review", db=db) == []


# ---------------------------------------------------------------- memory


def test_only_a_manager_writes_team_memory_and_marketers_keep_personal_notes(db, people):
    team = {"team": "national", "user_id": None}
    with pytest.raises(gate.Denied):
        memory.remember(people["marketer"], "r1", kind="procedural", text="Always say X", scope=team, source_type="manager_instruction", db=db)
    assert "only a manager" in deny_events(db, "memory.write")[0]["reason"]
    with pytest.raises(gate.Denied):
        memory.remember(people["sales"], "r2", kind="semantic", text="note", scope={"team": "national", "user_id": people["sales"].user_id}, db=db)
    with pytest.raises(gate.Denied):
        memory.remember(people["manager"], "r3", kind="procedural", text="x", scope={"team": "quebec", "user_id": None}, source_type="manager_instruction", db=db)

    instruction = memory.remember(people["manager"], "r4", kind="procedural", text="Always say X", scope=team, source_type="manager_instruction", auth_method="jwt+password", db=db)
    note = memory.remember(people["marketer"], "r5", kind="semantic", text="I like short copy", scope={"team": "national", "user_id": people["marketer"].user_id}, db=db)
    verdict = memory.remember(people["marketer"], "r6", kind="episodic", text="An ad was blocked", scope=team, source_type="agent", ttl_days=30, db=db)
    assert verdict["expires_at"] is not None and instruction["expires_at"] is None
    assert db.ledger.find_one({"run_id": "r4", "event": "decision"})["auth"] == {"method": "jwt+password"}

    seen_by_marketer = {m["text"] for m in memory.list_scoped(people["marketer"], db=db)}
    seen_by_manager = {m["text"] for m in memory.list_scoped(people["manager"], db=db)}
    assert seen_by_marketer == {"Always say X", "I like short copy", "An ad was blocked"}
    assert "I like short copy" not in seen_by_manager and note["visibility_roles"] == ["marketer"]
    assert memory.list_scoped(people["qc_manager"], db=db) == []
    assert memory.needs_step_up(people["manager"], team, "manager_instruction") and not memory.needs_step_up(people["marketer"], team, "agent")


def test_correct_supersedes_forget_tombstones_and_both_can_be_reverted(db, people):
    team = {"team": "national", "user_id": None}
    old = memory.remember(people["manager"], "r1", kind="procedural", text="End with A", scope=team, source_type="manager_instruction", db=db)
    new = memory.correct(people["manager"], "r2", old["id"], "End with B", db=db)
    assert new["supersedes"] == old["id"]
    assert [m["text"] for m in memory.list_scoped(people["marketer"], db=db)] == ["End with B"]
    assert {m["status"] for m in memory.list_scoped(people["manager"], db=db)} == {"active", "superseded"}

    with pytest.raises(memory.NotFound):
        memory.forget(people["qc_manager"], "r3", new["id"], "not mine", db=db)
    with pytest.raises(gate.Denied):
        memory.forget(people["marketer"], "r4", new["id"], "disagree", db=db)
    memory.forget(people["manager"], "r5", new["id"], "wrong", db=db)
    assert memory.list_scoped(people["marketer"], db=db) == []

    undo_forget = db.ledger.find_one({"run_id": "r5", "event": "outcome"})["undo"]
    assert memory.revert(undo_forget["ref"], db) == "forgotten memory restored"
    undo_correct = db.ledger.find_one({"run_id": "r2", "event": "outcome"})["undo"]
    assert "reactivated" in memory.revert(undo_correct["ref"], db)
    assert [m["text"] for m in memory.list_scoped(people["marketer"], db=db)] == ["End with A"]


# ---------------------------------------------------------------- policy edits


def test_policy_edit_needs_the_password_every_time_and_keeps_the_old_version(db, people):
    key = "credit.approval_claims"
    for bad in (None, "wrong"):
        with pytest.raises(security.StepUpFailed):
            fundamentals.update(people["manager"], "r-bad", key, text="x", reason="r", password=bad, db=db)
    assert len(deny_events(db, "fundamentals.update")) == 2 and fundamentals.get(key, db)["version"] == 2
    with pytest.raises(gate.Denied):
        fundamentals.update(people["marketer"], "r-marketer", key, text="x", reason="r", password=PASSWORD, db=db)

    before = fundamentals.get(key, db)["text"]
    after = fundamentals.update(people["manager"], "r-ok", key, text="Never promise approval.", reason="simplify", password=PASSWORD, db=db)
    assert after["version"] == 3 and after["text"] == "Never promise approval."
    (snapshot,) = fundamentals.history(key, db)
    assert snapshot["version"] == 2 and snapshot["snapshot"]["text"] == before and snapshot["reason"] == "simplify"

    decision, outcome = list(db.ledger.find({"run_id": "r-ok"}).sort("_id", 1))
    assert decision["auth"] == {"method": "jwt+password"} and decision["params"]["before"] == before and "password" not in decision["params"]
    assert outcome["undo"] == {"type": "fundamental.restore", "ref": {"key": key, "version": 2}}

    restored = fundamentals.restore(key, 2, people["manager"], db)
    assert restored["version"] == 2 and restored["text"] == before
    assert [h["version"] for h in fundamentals.history(key, db)] == [3, 2]


def test_retired_and_out_of_region_clauses_are_never_applicable(db):
    national = {c["key"] for c in fundamentals.applicable(["global", "CA"], "credit_card", db)}
    quebec = {c["key"] for c in fundamentals.applicable(["global", "CA", "CA-QC"], "credit_card", db)}
    assert "brand.holiday_tagline_2025" not in quebec
    assert quebec - national == {"regional.qc.french_language", "regional.qc.credit_terms"}
    assert fundamentals.current_versions(["brand.holiday_tagline_2025", "credit.bonus_conditions", "nope"], db) == {"brand.holiday_tagline_2025": None, "credit.bonus_conditions": 1, "nope": None}
