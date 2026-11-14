"""Round two, offline: what may be done and why, the tamper-evident ledger, crash recovery,
the lesion test, memory strength, image highlights and video. No network, no keys.
"""
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app.core import gate, llm
from app.models import Identity
from app.services import compliance, media, memory
from tests.conftest import PASSWORD
from tests.test_api_flow import AD, FIXED, FRENCH, QC_AD, RUNNING, api, canned, card, chat  # noqa: F401  (api is a fixture)

MANAGER = "manager.national@tamarack.test"
MARKETER = "marketer.national@tamarack.test"


def kinds(db, run_id, event=None):
    query = {"run_id": run_id, **({"event": event} if event else {})}
    return [(e["event"], e["action"], e.get("decision")) for e in db.ledger.find(query).sort("seq", 1)]


# ---------------------------------------------------------------- what may be done, decided before it is done


def test_each_of_the_five_checks_can_refuse_and_says_which_one_decided(db, people):
    manager, marketer, sales = people["manager"], people["marketer"], people["sales"]
    ok = gate.authorize(marketer, "compliance.check", db=db)
    assert ok.allow and [c["check"] for c in ok.checks] == ["identity", "role", "initiator", "state", "limits"]

    # 1. identity: the user was disabled, changed role, or had their access version raised after signing in
    db.users.update_one({"email": marketer.email}, {"$set": {"status": "disabled"}})
    assert gate.authorize(marketer, "compliance.check", db=db).decided_by == "identity"
    db.users.update_one({"email": marketer.email}, {"$set": {"status": "active", "role": "sales"}})
    assert gate.authorize(marketer, "compliance.check", db=db).decided_by == "identity"
    db.users.update_one({"email": marketer.email}, {"$set": {"role": "marketer", "auth_version": 3}})
    assert gate.authorize(marketer, "compliance.check", db=db).decided_by == "identity"
    db.users.update_one({"email": marketer.email}, {"$set": {"auth_version": 0}})
    assert gate.authorize(Identity(user_id="ghost", email="ghost@tamarack.test", role="manager", team="national"), "compliance.check", db=db).decided_by == "identity"

    # 2. role
    assert gate.authorize(sales, "compliance.check", db=db).decided_by == "role"

    # 3. initiator: a manager may approve; the agent acting for that same manager may not
    assert gate.authorize(manager, "campaign.approve", db=db).allow
    refused = gate.authorize(manager, "campaign.approve", initiator="agent", db=db)
    assert (refused.allow, refused.decided_by) == (False, "initiator") and "not by the agent" in refused.reason

    # 4. scope and state of the target
    assert gate.authorize(manager, "campaign.approve", facts={"target_team": "quebec"}, db=db).decided_by == "state"
    assert gate.authorize(manager, "campaign.approve", facts={"target_team": "national", "ad_status": "pending_review", "verdict": "blocked"}, db=db).decided_by == "state"
    assert gate.authorize(manager, "campaign.release", facts={"ad_status": "approved", "stale_changes": ["a clause changed"]}, db=db).decided_by == "state"
    assert gate.authorize(manager, "campaign.release", facts={"target_team": "national", "ad_status": "approved", "stale_changes": []}, db=db).allow

    # 5. limits: the run has used its budget
    db.runs.insert_one({"_id": "busy", "usage": {"model_calls": gate.DEFAULT_LIMITS["model_calls"]}})
    over = gate.authorize(marketer, "compliance.check", run_id="busy", db=db)
    assert (over.allow, over.decided_by) == (False, "limits") and "model calls" in over.reason


def test_the_agent_can_never_approve_release_or_change_policy_even_for_a_manager(db, people):
    ran = []
    for action in ("campaign.approve", "campaign.release", "fundamentals.update", "memory.forget", "run.rollback", "user.access"):
        with gate.acting_as("agent"), pytest.raises(gate.Denied) as refusal:
            gate.guarded(people["manager"], action, {}, f"agent-{action}", lambda: ran.append(action), db=db)
        assert refusal.value.check == "initiator"
        (event,) = db.ledger.find({"run_id": f"agent-{action}"})
        assert (event["decision"], event["decided_by"], event["initiator"]) == ("deny", "initiator", "agent")
    assert ran == []
    # The same manager, acting directly, is allowed.
    assert gate.guarded(people["manager"], "campaign.approve", {}, "direct", lambda: "done", db=db) == "done"
    decision = db.ledger.find_one({"run_id": "direct", "event": "decision"})
    assert decision["initiator"] == "human" and all(c["ok"] for c in decision["checks"])


def test_the_rules_are_data_and_a_refused_step_in_the_plan_means_nothing_runs(api, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "call_structured", lambda *a, **k: calls.append(k["label"]) or canned(*a, **k))
    # A rule in Atlas replaces the default: here the agent may no longer write memory.
    api.db.action_rules.insert_one({"_id": "memory.write", "initiators": ["human"]})
    rules = api.get("/policies/actions", headers=api.as_["marketer_national"]).json()
    rule = next(a for a in rules["actions"] if a["action"] == "memory.write")
    assert (rule["initiators"], rule["source"]) == (["human"], "action_rules") and rules["checks"][0] == "identity"

    run_id = str(uuid.uuid4())
    r = api.post("/chat", headers=api.as_["marketer_national"], json={"thread_id": "t-plan", "run_id": run_id, "ad": {**AD, "text": RUNNING}})
    assert r.json()["status"] == "denied"
    # The lane's third step would be refused, so the first never started: no model call, nothing filed.
    assert calls == [] and api.db.campaigns.count_documents({}) == 0
    assert kinds(api.db, run_id) == [("decision", "memory.write", "deny")]
    plan = api.db.runs.find_one({"_id": run_id})["plan"]
    assert [(p["action"], p["allow"]) for p in plan] == [("compliance.check", True), ("campaign.submit", True), ("memory.write", False)]


def test_a_run_over_its_budget_is_refused_its_next_step(api):
    api.db.action_rules.insert_one({"_id": "_limits", "per_run": {"steps": 2}})
    run_id = str(uuid.uuid4())
    r = api.post("/chat", headers=api.as_["marketer_national"], json={"thread_id": "t-budget", "run_id": run_id, "ad": {**AD, "text": RUNNING}})
    assert r.json()["status"] == "denied"
    last = list(api.db.ledger.find({"run_id": run_id}).sort("seq", 1))[-1]
    assert (last["decision"], last["decided_by"]) == ("deny", "limits") and "limit of 2 steps" in last["reason"]


def test_a_user_disabled_mid_run_loses_authority_at_the_next_step(api):
    run_id = str(uuid.uuid4())
    original = compliance.review
    marketer_id = str(api.db.users.find_one({"email": MARKETER})["_id"])

    def review_then_disable(*args, **kwargs):
        result = original(*args, **kwargs)
        # While the verdict is being produced, their manager disables them. It needs the manager's password.
        assert api.post(f"/users/{marketer_id}/access", headers=api.as_["manager_national"], json={"status": "disabled"}).status_code == 401
        done = api.post(f"/users/{marketer_id}/access", headers=api.as_["manager_national"], json={"status": "disabled", "password": PASSWORD, "reason": "left the team"})
        assert done.status_code == 200 and done.json()["status"] == "disabled"
        return result

    compliance.review = review_then_disable
    try:
        r = api.post("/chat", headers=api.as_["marketer_national"], json={"thread_id": "t-off", "run_id": run_id, "ad": {**AD, "text": RUNNING}})
    finally:
        compliance.review = original
    assert r.json()["status"] == "denied" and api.db.campaigns.count_documents({}) == 0
    last = list(api.db.ledger.find({"run_id": run_id}).sort("seq", 1))[-1]
    assert (last["action"], last["decision"], last["decided_by"]) == ("campaign.submit", "deny", "identity") and "disabled" in last["reason"]
    # They cannot sign in, a manager cannot disable themself, and a marketer cannot disable anyone.
    assert api.post("/auth/login", json={"email": MARKETER, "password": PASSWORD}).status_code == 401
    manager_id = str(api.db.users.find_one({"email": MANAGER})["_id"])
    assert api.post(f"/users/{manager_id}/access", headers=api.as_["manager_national"], json={"status": "disabled", "password": PASSWORD}).status_code == 403
    assert api.get("/users", headers=api.as_["marketer_quebec"]).status_code == 403


def test_authorize_answers_without_doing_anything(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "text": RUNNING, "name": "Blocked ad"})
    ad = card(reviewed, "campaign")
    before = api.db.ledger.count_documents({})
    ask = lambda who_, body: api.post("/authorize", headers=api.as_[who_], json=body).json()  # noqa: E731
    blocked = ask("manager_national", {"action": "campaign.approve", "campaign_id": ad["id"]})
    assert (blocked["allow"], blocked["decided_by"]) == (False, "state") and "has not passed" in blocked["reason"]
    assert ask("marketer_national", {"action": "campaign.approve", "campaign_id": ad["id"]})["decided_by"] == "role"
    assert ask("manager_national", {"action": "campaign.approve", "initiator": "agent"})["decided_by"] == "initiator"
    assert ask("manager_quebec", {"action": "campaign.approve", "campaign_id": ad["id"]})["reason"] == "there is no such ad in your scope"
    assert ask("marketer_national", {"action": "asset.regenerate", "campaign_id": ad["id"]})["allow"] is True
    assert api.db.ledger.count_documents({}) == before


# ---------------------------------------------------------------- the ledger: ordered, chained, tamper-evident


def test_the_chain_verifies_and_detects_an_edited_a_removed_and_a_reordered_event(db, people):
    for i in range(4):
        gate.guarded(people["marketer"], "compliance.check", {"n": i}, "chain", lambda: None, db=db)
    events = list(db.ledger.find({"run_id": "chain"}).sort("seq", 1))
    assert [e["seq"] for e in events] == list(range(8)) and events[0]["prev_hash"] == gate.GENESIS
    assert all(later["prev_hash"] == earlier["hash"] for earlier, later in zip(events, events[1:]))
    assert gate.verify_chain("chain", db) == {"run_id": "chain", "events": 8, "chained": 8, "intact": True, "head": events[-1]["hash"]}

    # Someone rewrites history: a denial is turned into an allow.
    db.ledger.update_one({"_id": events[2]["_id"]}, {"$set": {"reason": "edited afterwards"}})
    broken = gate.verify_chain("chain", db)
    assert (broken["intact"], broken["first_bad_seq"]) == (False, 2) and "changed after" in broken["problem"]
    db.ledger.update_one({"_id": events[2]["_id"]}, {"$set": {"reason": events[2]["reason"]}})
    assert gate.verify_chain("chain", db)["intact"] is True

    # Someone removes an event.
    db.ledger.delete_one({"_id": events[5]["_id"]})
    gone = gate.verify_chain("chain", db)
    assert (gone["intact"], gone["first_bad_seq"]) == (False, 6) and "missing" in gone["problem"]


def test_audit_shows_decisions_by_default_detail_on_request_and_verifies_over_the_api(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "text": RUNNING})
    run_id = reviewed["run_id"]
    plain = api.get(f"/audit?run_id={run_id}", headers=api.as_["marketer_national"]).json()
    detailed = api.get(f"/audit?run_id={run_id}&detail=true", headers=api.as_["marketer_national"]).json()
    assert {e["event"] for e in plain} == {"decision", "outcome"}
    findings = [e for e in detailed if e["event"] == "finding"]
    report = card(reviewed, "compliance_report")
    assert len(findings) == len(report["violations"]) and len(detailed) > len(plain)
    approval = next(f for f in findings if f["params"]["rests_on"].get("policy") == "credit.approval_claims")
    assert approval["params"]["quote"] == "Guaranteed approval!" and approval["confidence"]["score"] == 95 and approval["confidence"]["reasons"]

    assert api.get(f"/audit/verify?run_id={run_id}", headers=api.as_["marketer_national"]).json()["intact"] is True
    assert api.get(f"/audit/verify?run_id={run_id}", headers=api.as_["manager_quebec"]).json()["intact"] is None
    trace = api.get(f"/runs/{run_id}/trace", headers=api.as_["marketer_national"]).json()
    assert trace["chain"]["intact"] is True and [p["action"] for p in trace["plan"]] == ["compliance.check", "campaign.submit", "memory.write"]
    review_step = next(s for s in trace["steps"] if s.get("step") == "review")
    assert review_step["decision"]["decision"] == "allow" and [c["check"] for c in review_step["decision"]["checks"]][0] == "identity"
    assert review_step["outcome"]["result"]["status"] == "blocked" and review_step["outcome"]["duration_ms"] >= 0


def test_the_agent_is_refused_and_recorded_when_a_manager_asks_it_to_approve_in_chat(api):
    asked = chat(api, "manager_national", "approve the fall cashback ad")
    assert asked["status"] == "completed" and "cannot" in asked["reply"]
    (refusal,) = api.db.ledger.find({"run_id": asked["run_id"]})
    assert (refusal["action"], refusal["decision"], refusal["decided_by"], refusal["initiator"]) == ("campaign.approve", "deny", "initiator", "agent")


# ---------------------------------------------------------------- crash, resume, rollback


@pytest.fixture
def crashy(api, monkeypatch):
    """Fault injection on, crashed runs noticed at once, and every model call counted by label."""
    monkeypatch.setenv("ALLOW_FAULT_INJECTION", "true")
    monkeypatch.setattr(gate, "RUN_STALE_SECONDS", 0)
    api.calls = []
    monkeypatch.setattr(llm, "call_structured", lambda *a, **k: api.calls.append(k["label"]) or canned(*a, **k))
    return api


@pytest.mark.parametrize("step", ["review", "file", "remember"])
def test_a_review_that_crashes_after_any_step_resumes_to_the_same_result_with_nothing_done_twice(crashy, step):
    api, run_id = crashy, str(uuid.uuid4())
    body = {"thread_id": "t-crash", "run_id": run_id, "ad": {**AD, "text": RUNNING, "name": "Crash test"}}
    crashed = api.post("/chat", headers={**api.as_["marketer_national"], "X-Crash-After": step}, json=body)
    assert crashed.status_code == 500 and crashed.json()["error"] == "crashed"
    assert api.db.runs.find_one({"_id": run_id})["status"] == "running"  # exactly what a dead process leaves

    # Looking at the run notices the crash and records how far it got.
    seen = api.get(f"/runs/{run_id}", headers=api.as_["marketer_national"]).json()
    assert seen["status"] == "interrupted" and seen["resumable"] is True and seen["steps"][step]["status"] == "done"
    detected = api.db.ledger.find_one({"run_id": run_id, "event": "crash_detected"})
    assert step in detected["params"]["completed_steps"]

    # Only its owner can resume it.
    assert api.post(f"/runs/{run_id}/resume", headers=api.as_["manager_national"]).status_code == 403
    judged_before = api.calls.count("judge")
    resumed = api.post(f"/runs/{run_id}/resume", headers=api.as_["marketer_national"])
    assert resumed.status_code == 200, resumed.text
    out = resumed.json()
    assert (out["status"], out["resumed"], out["attempt"]) == ("completed", True, 2)
    assert card(out, "compliance_report")["verdict"] == "blocked" and card(out, "campaign")["version"] == 1

    # Nothing twice: one ad at version 1, one memory of the verdict, and the verdict was not paid for again.
    assert api.db.campaigns.count_documents({}) == 1 and api.db.campaigns.find_one({})["history"] == []
    assert api.db.memories.count_documents({"kind": "episodic"}) == 1
    assert api.calls.count("judge") == judged_before == 1 and api.calls.count("extract_claims") == 1
    # Each finding is on the ledger exactly once, even when the crash came between the verdict and recording them.
    assert api.db.ledger.count_documents({"run_id": run_id, "event": "finding"}) == len(card(out, "compliance_report")["violations"]) > 0
    reused = [e["params"]["step"] for e in api.db.ledger.find({"run_id": run_id, "event": "checkpoint"})]
    assert "review" in reused and api.db.ledger.count_documents({"run_id": run_id, "event": "resume"}) == 1
    assert api.db.runs.find_one({"_id": run_id})["status"] == "completed"
    assert gate.verify_chain(run_id, api.db)["intact"] is True
    # A finished run cannot be resumed again.
    assert api.post(f"/runs/{run_id}/resume", headers=api.as_["marketer_national"]).status_code == 403


@pytest.mark.parametrize("step", ["copy", "file"])
def test_a_regeneration_that_crashes_resumes_from_the_ad_as_it_was(crashy, step):
    api = crashy
    ad = card(chat(api, "marketer_national", ad={**AD, "text": RUNNING, "name": "Fall cashback email"}), "campaign")
    run_id = str(uuid.uuid4())
    crashed = api.post(f"/campaigns/{ad['id']}/regenerate", headers={**api.as_["marketer_national"], "X-Crash-After": step}, json={"run_id": run_id})
    assert crashed.status_code == 500
    judged = api.calls.count("judge")
    out = api.post(f"/runs/{run_id}/resume", headers=api.as_["marketer_national"]).json()
    # Without the snapshot, a run that had already filed version 2 would see a passing ad and do nothing.
    assert (out["status"], out["campaign"]["version"], out["campaign"]["source"], out["campaign"]["text"]) == ("regenerated", 2, "regenerated", FIXED)
    stored = api.db.campaigns.find_one({})
    assert stored["version"] == 2 and len(stored["history"]) == 1 and api.calls.count("judge") == judged


def test_a_step_that_took_effect_but_was_never_recorded_is_adopted_not_repeated(crashy, monkeypatch):
    api, run_id = crashy, str(uuid.uuid4())
    checkpoint = gate._checkpoint

    def die_before_recording_the_filing(db, run, step_key, result, dump):
        if step_key == "file":
            raise gate.SimulatedCrash("the process died after the ad was written and before the step was marked done")
        return checkpoint(db, run, step_key, result, dump)

    monkeypatch.setattr(gate, "_checkpoint", die_before_recording_the_filing)
    body = {"thread_id": "t-doubt", "run_id": run_id, "ad": {**AD, "text": RUNNING, "name": "In doubt"}}
    assert api.post("/chat", headers=api.as_["marketer_national"], json=body).status_code == 500
    monkeypatch.setattr(gate, "_checkpoint", checkpoint)
    assert api.db.campaigns.count_documents({}) == 1 and api.db.runs.find_one({"_id": run_id})["steps"]["file"]["status"] == "started"
    assert "file" in api.get(f"/runs/{run_id}", headers=api.as_["marketer_national"]).json()["steps"]
    assert api.db.ledger.find_one({"run_id": run_id, "event": "crash_detected"})["params"]["in_doubt_steps"] == ["file"]

    out = api.post(f"/runs/{run_id}/resume", headers=api.as_["marketer_national"]).json()
    assert out["status"] == "completed" and api.db.campaigns.count_documents({}) == 1 and api.db.campaigns.find_one({})["version"] == 1
    adopted = api.db.ledger.find_one({"run_id": run_id, "event": "checkpoint", "params.step": "file"})
    assert "kept, not repeated" in adopted["result"]["summary"]


def test_rolling_back_a_crashed_run_also_removes_what_a_half_finished_step_left_behind(crashy, monkeypatch):
    api, run_id = crashy, str(uuid.uuid4())
    real_event = gate._event

    def die_while_filing(db, identity, run, event, action, **fields):
        # The ad is written, then the process dies before the outcome reaches the ledger.
        if run == run_id and event == "outcome" and action == "campaign.submit":
            raise gate.SimulatedCrash("died between the write and the ledger")
        return real_event(db, identity, run, event, action, **fields)

    monkeypatch.setattr(gate, "_event", die_while_filing)
    body = {"thread_id": "t-rb", "run_id": run_id, "ad": {**AD, "text": RUNNING, "name": "Half filed"}}
    assert api.post("/chat", headers=api.as_["marketer_national"], json=body).status_code == 500
    monkeypatch.setattr(gate, "_event", real_event)
    assert api.db.campaigns.find_one({})["status"] == "pending_review"
    assert not api.db.ledger.find_one({"run_id": run_id, "event": "outcome", "action": "campaign.submit"})

    rolled = api.post(f"/runs/{run_id}/rollback", headers=api.as_["manager_national"])
    assert rolled.status_code == 200 and rolled.json()["status"] == "rolled_back"
    assert rolled.json()["undone"] == ["unrecorded filing: ad marked rolled back"]
    assert api.db.campaigns.find_one({})["status"] == "rolled_back"
    assert api.get("/campaigns", headers=api.as_["marketer_national"]).json() == []


def test_a_run_that_failed_on_an_outside_service_can_be_resumed_without_paying_for_the_verdict_again(crashy, monkeypatch):
    from app.core import embeddings

    api, run_id = crashy, str(uuid.uuid4())
    working = embeddings.embed_documents

    def limited(texts):
        raise embeddings.EmbeddingRateLimited("the embedding service is rate limited")

    monkeypatch.setattr(embeddings, "embed_documents", limited)
    body = {"thread_id": "t-429", "run_id": run_id, "ad": {**AD, "text": RUNNING}}
    assert api.post("/chat", headers=api.as_["marketer_national"], json=body).status_code == 429
    assert api.db.runs.find_one({"_id": run_id})["status"] == "error" and api.db.campaigns.count_documents({}) == 0
    monkeypatch.setattr(embeddings, "embed_documents", working)
    out = api.post(f"/runs/{run_id}/resume", headers=api.as_["marketer_national"]).json()
    assert out["status"] == "completed" and api.calls.count("judge") == 1 and api.db.campaigns.count_documents({}) == 1


def test_fault_injection_is_off_unless_it_is_switched_on(api):
    r = api.post("/chat", headers={**api.as_["marketer_national"], "X-Crash-After": "review"}, json={"thread_id": "t-off", "ad": {**AD, "text": FIXED}})
    assert r.status_code == 200 and r.json()["status"] == "completed"


# ---------------------------------------------------------------- the lesion test and memory strength


INSTRUCTION = {"kind": "procedural", "text": "Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'", "scope": {"team": "quebec", "user_id": None}, "reason": "legal asked", "password": PASSWORD}


def test_the_lesion_test_shows_the_memory_that_changed_the_verdict(api):
    saved = api.post("/memories", headers=api.as_["manager_quebec"], json=INSTRUCTION).json()
    reviewed = chat(api, "marketer_quebec", ad={**QC_AD, "text": FRENCH, "name": "Courriel remises"})
    assert card(reviewed, "compliance_report")["verdict"] == "needs_changes"

    result = api.post(f"/runs/{reviewed['run_id']}/attribution", headers=api.as_["marketer_quebec"])
    assert result.status_code == 200, result.text
    out = result.json()
    (tested,) = out["tested"]
    assert out["control_reproduced_original"] is True and out["memories_in_view"] >= 1
    assert (tested["memory_id"], tested["effect"], tested["causal"]) == (saved["id"], "decisive", True)
    assert (tested["with"]["verdict"], tested["without"]["verdict"]) == ("needs_changes", "pass") and len(tested["findings_lost"]) == 1
    # It is on the ledger, on the original run, and the original ad was not touched.
    event = api.db.ledger.find_one({"run_id": out["run_id"], "event": "attribution"})
    assert event["params"]["memory_id"] == saved["id"] and event["params"]["effect"] == "decisive"
    assert api.db.runs.find_one({"_id": reviewed["run_id"]})["attribution"]["tested"][0]["effect"] == "decisive"
    assert api.db.campaigns.count_documents({}) == 1 and api.db.campaigns.find_one({})["version"] == 1

    # A review that rests on no memory has nothing to remove. Another team cannot test this run.
    clean = chat(api, "marketer_national", ad={**AD, "text": RUNNING})
    assert api.post(f"/runs/{clean['run_id']}/attribution", headers=api.as_["marketer_national"]).status_code == 409
    assert api.post(f"/runs/{reviewed['run_id']}/attribution", headers=api.as_["manager_national"]).status_code == 404


def test_strength_fades_with_disuse_but_a_binding_decision_never_does():
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=90)
    assert memory.current_strength({"kind": "semantic", "authority": "background", "strength": 1.0, "created_at": old}, now) == pytest.approx(0.5)
    assert memory.current_strength({"kind": "episodic", "strength": 1.0, "created_at": old}, now) == pytest.approx(0.25)
    assert memory.current_strength({"kind": "procedural", "authority": "binding", "strength": 1.0, "created_at": old}, now) == 1.0
    assert memory.current_strength({"kind": "episodic", "strength": 1.0, "created_at": old, "last_reinforced_at": now}, now) == pytest.approx(1.0)
    assert memory.current_strength({"kind": "episodic", "strength": 0.3, "created_at": now - timedelta(days=900)}, now) == memory.STRENGTH_MIN
    # Strength only nudges the order inside the same standing; it can never outweigh a real difference in relevance.
    shaped = lambda i, s: {"id": i, "authority": "background", "date": "2026-01-01", "strength": s}  # noqa: E731
    assert [m["id"] for m in memory.select([(shaped("weak", 0.2), 0.60), (shaped("strong", 2.0), 0.55)], 1)] == ["strong"]
    assert [m["id"] for m in memory.select([(shaped("weak", 0.2), 0.70), (shaped("strong", 2.0), 0.55)], 1)] == ["weak"]
    assert memory.STRENGTH_WEIGHT * (memory.STRENGTH_MAX - memory.STRENGTH_MIN) < 0.1


def test_a_managers_decision_strengthens_or_weakens_the_memories_the_review_used(api):
    saved = api.post("/memories", headers=api.as_["manager_national"], json={**INSTRUCTION, "text": "National card emails should mention the mobile app.", "scope": {"team": "national", "user_id": None}}).json()
    strength = lambda: api.db.memories.find_one({"text": "National card emails should mention the mobile app."})["strength"]  # noqa: E731
    assert strength() == 1.0

    # The review passed and the manager approved: agreement strengthens what the review had in view.
    ad = card(chat(api, "marketer_national", ad={**AD, "text": FIXED, "name": "Clean ad"}), "campaign")
    approved = api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["manager_national"], json={})
    assert approved.status_code == 200 and strength() == pytest.approx(1.1)
    step = api.db.ledger.find_one({"run_id": approved.json()["run_id"], "event": "outcome", "params.step": {"$exists": False}, "undo.type": "memory.strength"})
    assert step["undo"]["ref"]["changes"] == [{"id": saved["id"], "strength": 1.0, "at": None}]

    # The review passed and the manager rejected: a surprise. The memories weaken and the correction is kept, stronger.
    other = card(chat(api, "marketer_national", ad={**AD, "text": FIXED + " Download the app.", "name": "Second ad"}), "campaign")
    rejected = api.post(f"/campaigns/{other['id']}/reject", headers=api.as_["manager_national"], json={"feedback": "The app is not available in Quebec yet; do not promote it nationally."})
    assert rejected.status_code == 200 and strength() == pytest.approx(1.1 * memory.WEAKEN_FACTOR)
    correction = api.db.memories.find_one({"source.type": "review_feedback"})
    assert correction["strength"] == memory.SURPRISE_STRENGTH and correction["surprise"] is True and "not available in Quebec" in correction["text"]

    # Rolling the rejection back restores the strength and removes the correction.
    rolled = api.post(f"/runs/{rejected.json()['run_id']}/rollback", headers=api.as_["manager_national"]).json()
    assert strength() == pytest.approx(1.1) and api.db.memories.find_one({"source.type": "review_feedback"})["status"] == "forgotten"
    assert any("strength" in line for line in rolled["undone"])


def test_faded_memories_are_listed_for_a_manager_to_confirm(api):
    long_ago = datetime.now(timezone.utc) - timedelta(days=200)
    api.db.memories.insert_one({
        "kind": "semantic", "authority": "background", "text": "Spring campaign used a green palette.", "scope": {"team": "national", "user_id": None},
        "visibility_roles": ["manager", "marketer"], "status": "active", "strength": 1.0, "created_at": long_ago, "expires_at": None, "embedding": [0.0] * 8,
    })
    (faded,) = api.get("/memories/fading", headers=api.as_["manager_national"]).json()
    assert faded["current_strength"] < memory.FADING_BELOW and faded["standing"] == "background"
    assert api.post(f"/memories/{faded['id']}/confirm", headers=api.as_["marketer_national"]).status_code == 403
    assert api.post(f"/memories/{faded['id']}/confirm", headers=api.as_["manager_national"]).json()["strength"] == 1.0
    assert api.get("/memories/fading", headers=api.as_["manager_national"]).json() == []


def test_past_verdicts_on_the_same_rule_are_drafted_into_one_lesson_and_saved_only_with_the_password(api, monkeypatch):
    from app.services import consolidation

    for name in ("First", "Second"):
        chat(api, "marketer_national", ad={**AD, "text": RUNNING, "name": name})
    assert api.db.memories.count_documents({"kind": "episodic"}) == 2
    monkeypatch.setattr(llm, "call_structured", lambda *a, **k: consolidation.Lesson(pattern_found=True, lesson="Never promise approval in a card ad.", explanation="Both were blocked for it.") if k["label"] == "consolidate" else canned(*a, **k))

    assert api.post("/memories/consolidate", headers=api.as_["marketer_national"]).status_code == 403
    drafted = api.post("/memories/consolidate", headers=api.as_["manager_national"]).json()
    proposal = next(p for p in drafted["proposals"] if p["policy_key"] == "credit.approval_claims")
    assert proposal["episode_count"] == 2 and proposal["card"]["requires_password"] is True
    assert api.db.memories.count_documents({"kind": "procedural"}) == 0  # a draft only

    body = {"kind": "procedural", "text": proposal["card"]["after"], "scope": proposal["card"]["scope"], "consolidated_from": proposal["card"]["consolidated_from"]}
    assert api.post("/memories", headers=api.as_["manager_national"], json=body).status_code == 401
    lesson = api.post("/memories", headers=api.as_["manager_national"], json={**body, "password": PASSWORD}).json()
    stored = api.db.memories.find_one({"text": "Never promise approval in a card ad."})
    assert len(stored["consolidated_from"]) == 2 and stored["authority"] == "guidance" and stored["always"] is False and lesson["id"]
    # The same group is not offered again.
    again = api.post("/memories/consolidate", headers=api.as_["manager_national"]).json()
    assert all(p["policy_key"] != "credit.approval_claims" for p in again["proposals"])


# ---------------------------------------------------------------- image highlights and video


def test_findings_are_drawn_on_a_copy_of_the_image_with_a_legend():
    picture = Image.new("RGB", (800, 600), "white")
    raw = io.BytesIO()
    picture.save(raw, format="PNG")
    findings = [
        {"fundamental_key": "REG-03", "materiality": "material", "explanation": "An athlete appears in a betting ad.", "quote": "Jake Moreau"},
        {"fundamental_key": "REG-14", "materiality": "disclosure", "explanation": "The disclaimer is missing.", "quote": ""},
    ]
    highlights = [{"finding": 0, "box": [0.25, 0.25, 0.5, 0.5], "kind": "text"}, {"finding": 1, "box": None, "kind": "missing"}]
    marked = Image.open(io.BytesIO(media.annotate_image_bytes(raw.getvalue(), findings, highlights))).convert("RGB")
    assert marked.width == 800 and marked.height > 600          # the picture, then the legend underneath
    red = lambda p: p[0] > 150 and p[1] < 110 and p[2] < 110     # noqa: E731
    assert red(marked.getpixel((200, 300))) and red(marked.getpixel((400, 150)))   # the box edges, where they were asked for
    assert marked.getpixel((300, 225)) == (255, 255, 255)        # the inside of the box is untouched
    assert media.finding_label(findings[0]).startswith("REG-03")


def _tiny_video(tmp_path, frames=30) -> bytes:
    import cv2
    import numpy

    path = str(tmp_path / "ad.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(frames):
        frame = numpy.full((240, 320, 3), 255 if i < frames // 2 else 40, dtype=numpy.uint8)
        writer.write(frame)
    writer.release()
    return open(path, "rb").read()


def test_a_video_is_read_as_speech_plus_on_screen_text_and_goes_through_the_same_review(api, tmp_path, monkeypatch):
    data = _tiny_video(tmp_path)
    assert media.kind_of("video/mp4") == "video" and media.kind_of("video/quicktime") == "video"
    seen = {}

    def model(model_, schema, **k):
        if k["label"] == "read_video":
            seen["frames"] = sum(1 for block in k["user"] if block["type"] == "image")
            return media.VideoReading(on_screen_text="Guaranteed approval! Apply today.", visual_notes="A card on a desk.", fine_print_present=False, fine_print_legible=True, people_present=False)
        return canned(model_, schema, **k)

    monkeypatch.setattr(llm, "call_structured", model)
    monkeypatch.setattr(media, "video_speech", lambda path: "Enjoy 0% interest for 12 months and earn $300 cash back.")
    reading = media.read_video_bytes(data, "video/mp4")
    assert seen["frames"] == media.MAX_FRAMES and reading["frames"] == media.MAX_FRAMES and reading["seconds"] == 3.0
    assert reading["text"] == "Spoken: Enjoy 0% interest for 12 months and earn $300 cash back.\nOn screen: Guaranteed approval! Apply today."

    # The same flow as any ad: reviewed, filed as a video, and not offered for regeneration.
    monkeypatch.setattr(media, "open_file", lambda file_id, db=None: (data, "video/mp4"))
    reviewed = chat(api, "marketer_national", file_id="64b000000000000000000001", ad={**AD, "name": "Fall cashback video"})
    report, ad = card(reviewed, "compliance_report"), card(reviewed, "campaign")
    assert report["verdict"] == "blocked" and "credit.approval_claims" in {v["fundamental_key"] for v in report["violations"]}
    assert (ad["modality"], ad["asset"]["type"]) == ("video", "video") and report["highlights"] == [] and "regenerate" not in reviewed["reply"]
    assert any("video" in reason for reason in report["confidence"]["reasons"])
    read_step = api.db.ledger.find_one({"run_id": reviewed["run_id"], "event": "outcome", "step": "read"})
    assert "3-second video" in read_step["result"]["summary"]
    regen = api.post(f"/campaigns/{ad['id']}/regenerate", headers=api.as_["marketer_national"], json={}).json()
    assert regen["status"] == "failed" and "video" in regen["reply"] and api.db.campaigns.find_one({})["version"] == 1
