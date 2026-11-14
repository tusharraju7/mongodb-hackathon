"""The whole API, wired together, on an in-memory database with the model calls canned.

This proves the routers, the graph, the lanes, the gate and the services agree with each other:
who may do what, what lands on the ledger, and that the state changes are the ones the docs promise.
It does not prove the prompts or vector search; scripts/dry_run.py and scripts/smoke.py do that live.
"""
import re
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import graph, lanes
from app.core import db as db_module
from app.core import llm, security
from app.models import Extraction, ExtractedClaim, JudgeFinding, JudgeOutput, RepairOutput
from app.services import campaigns, compliance, fundamentals, memory, offers
from tests.conftest import PASSWORD

RUNNING = "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."
FIXED = "Enjoy 0% interest on purchases for 10 months, then 20.99%. Earn $300 cash back after $1,500 in purchases in your first 3 months. Apply today. Subject to credit approval. Conditions apply. Unsubscribe: tamarack.test/unsubscribe"
FRENCH = "Obtenez 300 $ de remise en argent après 1 500 $ d'achats au cours de vos 3 premiers mois. Taux d'intérêt de 0 % sur les achats pendant 10 mois, puis 20,99 %. Des conditions s'appliquent. Se désabonner : tamarack.test/desabonnement"
INSTRUCTION = "Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'"
AD = {"product": "credit_card", "offer_id": "TCB-FALL-2026", "region": "CA", "channel": "email", "budget": {"amount": 20000, "currency": "CAD"}}
QC_AD = {**AD, "region": "CA-QC", "language": "fr", "budget": {"amount": 6000, "currency": "CAD"}}


def _ad_text(user: str) -> str:
    return re.search(r"<ad[^>]*>\n(.*?)\n</ad>", user, re.S).group(1)


def canned(model, schema, *, system, user, label, usage=None, run_id=None, intent=None):
    """Stands in for the model. Deterministic, and just enough to drive each lane."""
    if usage is not None:
        usage.add(label, {"input_tokens": 100, "output_tokens": 20})
    if label == "route":
        message = re.search(r"<message>\n(.*?)\n</message>", user, re.S).group(1).lower()
        intent = (
            "memory_update" if "from now on" in message else "regenerate" if "regenerate" in message else "review" if "review" in message
            else "approve_release" if "approve" in message else "ask" if "?" in message else "other"
        )
        return graph.Route(intent=intent)
    if label == "extract_claims":
        text = _ad_text(user)
        claims = []
        if "Guaranteed approval" in text:
            claims.append(ExtractedClaim(type="approval", quote="Guaranteed approval!"))
        m = re.search(r"0\s?% (?:interest[^.]*?)?(?:for|pendant) (\d+) (?:months|mois)", text)
        if m:
            claims.append(ExtractedClaim(type="intro_rate", quote=m.group(0), rate_percent=0, months=int(m.group(1))))
        m = re.search(r"\$300 cash back|300 \$ de remise en argent", text)
        if m:
            claims.append(ExtractedClaim(type="rewards_bonus", quote=m.group(0), amount=300))
        fr = "remise" in text
        return Extraction(claims=claims, cta="Apply today", tone="plain", language="fr" if fr else "en", description="An ad about $300 cash back on the card.", summary="Cash back offer ad.")
    if label == "judge":
        text = _ad_text(user)
        findings = []
        if "Guaranteed approval" in text:
            findings.append(JudgeFinding(source="policy", ref="credit.approval_claims", quote="Guaranteed approval!", explanation="Promises approval.", reasoning="The ad promises approval. Policy forbids it.", fix="Remove it.", certainty="clear"))
        if "INVENTED" in text:
            findings.append(JudgeFinding(source="policy", ref="credit.bonus_conditions", quote="words that are not in the ad", explanation="x", reasoning="x", fix="x", certainty="clear"))
        memo = re.search(r"- id (\S+) \[binding internal decision[^\]]*\]: [^\n]*Sous réserve", user)
        if memo and "Sous réserve" not in text:
            findings.append(JudgeFinding(source="memory", ref=memo.group(1), quote="", explanation="The required line is missing.", reasoning="The team requires the line. The ad does not carry it.", fix="Add the line.", certainty="clear"))
        french = "remise" in text
        fixed = (text.replace(" Des conditions", " Sous réserve de l'approbation du crédit. Des conditions") if french else FIXED) if findings or "12 months" in text else text
        return JudgeOutput(findings=findings, summary="Summary of the review.", corrected_copy=fixed, corrected_copy_language="fr" if french else "en")
    if label == "repair_copy":
        return RepairOutput(corrected_copy=FIXED)
    if label in ("answer", "answer_full_text"):
        return lanes.Answer(answer="$300 after $1,500 in purchases in the first 3 months.", ad="A", basis="facts_and_offer")
    if label == "draft_change":
        return lanes.DraftChange(kind="new_instruction", text=INSTRUCTION, memory_kind="procedural")
    raise AssertionError(f"unexpected model call: {label}")


class FlowSources:
    """Reads the in-memory database with the same scoping as the Atlas queries, minus vector ranking."""

    def __init__(self, database):
        self.db = database

    def offer(self, offer_id):
        return offers.get(offer_id, self.db)

    def applicable_clauses(self, regions, product):
        return fundamentals.applicable(regions, product, self.db)

    def similar_clauses(self, vectors, regions, product, k):
        return [[] for _ in vectors]

    def recall(self, identity, vectors, kinds, per_query, budget):
        at = datetime.now(timezone.utc)
        hits = [m for m in self.db.memories.find({"kind": {"$in": kinds}}) if memory._readable(m, identity, at)]
        return memory.select([(memory.for_review(m, str(m["_id"])), 1.0) for m in hits], budget)


@pytest.fixture
def api(db, monkeypatch):
    class FakeClient:
        admin = type("A", (), {"command": staticmethod(lambda *_: {"ok": 1})})()

        def __getitem__(self, name):
            return db

    monkeypatch.setattr(db_module, "get_client", lambda: FakeClient())
    monkeypatch.setattr(security, "_secret", lambda: "test-secret-that-is-long-enough-for-hs256-signing")
    monkeypatch.setattr(llm, "call_structured", canned)
    monkeypatch.setattr(compliance, "default_sources", lambda: FlowSources(db))
    monkeypatch.setattr(lanes, "default_sources", lambda: FlowSources(db))
    monkeypatch.setattr(campaigns, "search_by_vector", lambda identity, vector, k=1, database=None: list(db.campaigns.find({"team": identity.team, "status": {"$in": campaigns.visible_statuses(identity)}}).limit(k)))
    test_graph = graph.build(InMemorySaver())
    monkeypatch.setattr(graph, "chat_graph", lambda: test_graph)

    from app.main import app

    client = TestClient(app)

    def login(email):
        r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    client.as_ = {name: login(f"{name.replace('_', '.')}@tamarack.test") for name in ("manager_national", "marketer_national", "sales_national", "manager_quebec", "marketer_quebec")}
    client.db = db
    return client


def chat(api, who, message="", **body):
    run_id = str(uuid.uuid4())
    r = api.post("/chat", headers=api.as_[who], json={"thread_id": "t1", "run_id": run_id, "message": message, **body})
    assert r.status_code == 200, r.text
    return r.json()


def card(reply, kind):
    return next(c["data"] for c in reply["cards"] if c["type"] == kind)


def events(api, run_id):
    return [(e["event"], e["action"], e.get("decision")) for e in api.db.ledger.find({"run_id": run_id}).sort("_id", 1)]


def test_login_rejects_a_wrong_password_and_tokens_carry_the_role(api):
    assert api.post("/auth/login", json={"email": "sales.national@tamarack.test", "password": "nope"}).status_code == 401
    assert api.get("/me", headers=api.as_["sales_national"]).json()["role"] == "sales"
    assert api.get("/campaigns").status_code == 401


def test_review_regenerate_approve_release_then_a_sales_question(api):
    # UC1: the running example is blocked, with the decision on the ledger before the outcome.
    reviewed = chat(api, "marketer_national", ad={**AD, "text": RUNNING, "name": "Fall cashback email"})
    report, ad = card(reviewed, "compliance_report"), card(reviewed, "campaign")
    assert (reviewed["intent"], report["verdict"], report["route"]) == ("review", "blocked", "human_review")
    cited = sorted({v["fundamental_key"] for v in report["violations"]})
    assert cited == ["brand.required_footer", "credit.approval_claims", "policy.offer_accuracy", "regional.ca.email_consent"]
    approval_finding = next(v for v in report["violations"] if v["fundamental_key"] == "credit.approval_claims")
    assert approval_finding["confidence"]["score"] == 95 and approval_finding["evidence"]["policy_excerpt"].startswith("Do not promise")
    assert report["confidence"] == {**report["confidence"], "score": 100, "band": "high"}
    assert (ad["status"], ad["version"], ad["modality"]) == ("pending_review", 1, "text")
    assert reviewed["tokens"]["in"] > 0
    log = events(api, reviewed["run_id"])
    assert log[:2] == [("decision", "compliance.check", "allow"), ("outcome", "compliance.check", None)]
    assert ("outcome", "campaign.submit", None) in log and ("outcome", "memory.write", None) in log
    assert api.db.runs.find_one({"_id": reviewed["run_id"]})["intent"] == "review"

    # A blocked ad cannot be approved, even by a manager.
    assert api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["manager_national"], json={}).status_code == 409

    # Regenerate: copy is checked before anything is filed; the new version passes and awaits approval.
    regen = api.post(f"/campaigns/{ad['id']}/regenerate", headers=api.as_["marketer_national"], json={}).json()
    assert (regen["status"], regen["attempts"], regen["report"]["verdict"]) == ("regenerated", 1, "pass")
    assert (regen["campaign"]["version"], regen["campaign"]["source"], regen["campaign"]["derived_from"]) == (2, "regenerated", 1)
    assert regen["campaign"]["text"] == FIXED

    # Sales cannot see it yet, cannot regenerate it, and a marketer cannot approve it.
    assert api.get("/campaigns", headers=api.as_["sales_national"]).json() == []
    assert api.post(f"/campaigns/{ad['id']}/regenerate", headers=api.as_["sales_national"], json={}).status_code == 404
    assert api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["marketer_national"], json={}).status_code == 403

    approved = api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["manager_national"], json={})
    assert approved.status_code == 200 and approved.json()["approved"] is True
    released = api.post(f"/campaigns/{ad['id']}/release", headers=api.as_["marketer_national"], json={})
    assert released.status_code == 200 and released.json()["status"] == "released"

    # UC5: now sales can ask, and gets the ad itself with where the answer came from.
    answer = chat(api, "sales_national", "A customer got an email about $300 cash back. What are the conditions?")
    assert answer["intent"] == "ask" and card(answer, "campaign")["id"] == ad["id"]
    assert answer["grounding"]["band"] == "high" and {s["type"] for s in answer["grounding"]["sources"]} == {"ad", "offer"}

    # Sales asking for something they may not do: a fixed refusal, a recorded denial, no lane model call.
    refused = chat(api, "sales_national", "From now on, all ads must mention our app")
    assert refused["status"] == "denied" and refused["cards"] == []
    assert events(api, refused["run_id"]) == [("decision", "memory.write", "deny")]
    assert chat(api, "sales_national", "approve the Quebec ad please")["status"] == "denied"


def test_a_finding_with_an_invented_quote_is_dropped(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "text": FIXED + " INVENTED"})
    report = card(reviewed, "compliance_report")
    assert report["verdict"] == "pass" and report["violations"] == []
    assert {"check": "dropped_findings", "detail": 1} in report["passed_checks"]


def test_an_unknown_offer_stops_the_review_and_nothing_is_filed(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "offer_id": "NO-SUCH-OFFER", "text": RUNNING})
    assert reviewed["status"] == "needs_input" and card(reviewed, "compliance_report")["missing_inputs"] == ["offer_id"]
    assert api.db.campaigns.count_documents({}) == 0


def test_a_manager_instruction_changes_the_next_verdict_and_stays_inside_the_team(api):
    # Today the French ad passes.
    first = chat(api, "marketer_quebec", ad={**QC_AD, "text": FRENCH, "name": "Courriel remises"})
    ad = card(first, "campaign")
    assert card(first, "compliance_report")["verdict"] == "pass"

    # UC4: the agent only drafts. Nothing is saved by the chat turn.
    drafted = chat(api, "manager_quebec", "From now on, Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'")
    proposal = card(drafted, "memory_change")
    assert (proposal["status"], proposal["requires_password"], proposal["scope"]) == ("proposed", True, {"team": "quebec", "user_id": None})
    assert api.db.memories.count_documents({"kind": "procedural"}) == 0

    # Saving it needs the password, every time.
    body = {"kind": proposal["kind"], "text": proposal["after"], "scope": proposal["scope"], "reason": "legal asked"}
    assert api.post("/memories", headers=api.as_["manager_quebec"], json=body).status_code == 401
    assert api.post("/memories", headers=api.as_["manager_quebec"], json={**body, "password": "wrong"}).status_code == 401
    assert api.post("/memories", headers=api.as_["marketer_quebec"], json={**body, "password": PASSWORD}).status_code == 403
    saved = api.post("/memories", headers=api.as_["manager_quebec"], json={**body, "password": PASSWORD})
    assert saved.status_code == 200
    memory_id = saved.json()["id"]
    write = api.db.ledger.find_one({"run_id": saved.json()["run_id"], "event": "decision", "decision": "allow"})
    assert write["auth"] == {"method": "jwt+password"} and "password" not in write["params"]

    # The same ad is now flagged, citing that memory; with memory off it passes again.
    again = chat(api, "marketer_quebec", ad={"campaign_id": ad["id"]}, message="review it again")
    report = card(again, "compliance_report")
    assert report["verdict"] == "needs_changes" and report["violations"][0]["memory_id"] == memory_id
    assert report["violations"][0]["confidence"]["score"] == 85
    assert memory_id in [m["id"] for m in again["memories_used"]]
    replay = api.post("/compliance/check", headers=api.as_["marketer_quebec"], json={**QC_AD, "text": FRENCH, "use_memory": False}).json()
    assert replay["verdict"] == "pass" and replay["memories_used"] == []

    # The national team never sees it, in the list or in a review.
    assert all(m["id"] != memory_id for m in api.get("/memories", headers=api.as_["manager_national"]).json())
    national = api.post("/compliance/check", headers=api.as_["marketer_national"], json={**AD, "text": FIXED}).json()
    assert national["verdict"] == "pass" and memory_id not in national["memories_used"]

    # Forgetting it also needs the password; afterwards the ad passes again.
    assert api.request("DELETE", f"/memories/{memory_id}", headers=api.as_["manager_quebec"], json={"reason": "withdrawn"}).status_code == 401
    assert api.request("DELETE", f"/memories/{memory_id}", headers=api.as_["manager_quebec"], json={"reason": "withdrawn", "password": PASSWORD}).status_code == 204
    after = api.post("/compliance/check", headers=api.as_["marketer_quebec"], json={**QC_AD, "text": FRENCH}).json()
    assert after["verdict"] == "pass"


def test_policy_edit_blocks_a_release_and_rollback_restores_it(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "text": FIXED, "name": "Clean ad"})
    ad = card(reviewed, "campaign")
    assert api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["manager_national"], json={}).status_code == 200

    clause = next(c for c in api.get("/fundamentals", headers=api.as_["manager_national"]).json() if c["key"] == "credit.intro_rate_disclosure")
    edit = {"text": "Stricter wording.", "reason": "regulator letter"}
    assert api.put(f"/fundamentals/{clause['id']}", headers=api.as_["manager_national"], json=edit).status_code == 401
    assert api.put(f"/fundamentals/{clause['id']}", headers=api.as_["marketer_national"], json={**edit, "password": PASSWORD}).status_code == 403
    edited = api.put(f"/fundamentals/{clause['id']}", headers=api.as_["manager_national"], json={**edit, "password": PASSWORD})
    assert edited.status_code == 200 and edited.json()["version"] == 4
    assert api.get(f"/fundamentals/{clause['id']}/history", headers=api.as_["manager_national"]).json()[0]["version"] == 3

    stale = api.post(f"/campaigns/{ad['id']}/release", headers=api.as_["marketer_national"], json={})
    assert stale.status_code == 409 and stale.json()["changes"] == ["credit.intro_rate_disclosure changed from version 3 to 4"]
    assert api.get(f"/campaigns/{ad['id']}", headers=api.as_["marketer_national"]).json()["status"] == "pending_review"

    # Only a manager can roll back; rollback restores version 3 and writes rollback events on the run.
    edit_run = edited.json()["run_id"]
    assert api.post(f"/runs/{edit_run}/rollback", headers=api.as_["marketer_national"]).status_code in (403, 404)
    rolled = api.post(f"/runs/{edit_run}/rollback", headers=api.as_["manager_national"])
    assert rolled.status_code == 200 and rolled.json()["undone"] == ["credit.intro_rate_disclosure restored to version 3"]
    assert rolled.json()["status"] == "rolled_back"
    assert ("rollback", "fundamentals.update", None) in events(api, edit_run)

    assert api.post(f"/campaigns/{ad['id']}/approve", headers=api.as_["manager_national"], json={}).status_code == 200
    assert api.post(f"/campaigns/{ad['id']}/release", headers=api.as_["marketer_national"], json={}).json()["status"] == "released"


def test_stop_halts_a_run_before_its_next_step(api):
    run_id = str(uuid.uuid4())
    original = compliance.review

    def review_then_stop(*args, **kwargs):
        result = original(*args, **kwargs)
        # Someone presses Stop while the verdict is being produced.
        assert api.post(f"/runs/{run_id}/stop", headers=api.as_["marketer_national"]).json()["stop_requested"] is True
        return result

    compliance.review = review_then_stop
    try:
        r = api.post("/chat", headers=api.as_["marketer_national"], json={"thread_id": "t-stop", "run_id": run_id, "ad": {**AD, "text": RUNNING}})
    finally:
        compliance.review = original
    assert r.json()["status"] == "stopped"
    assert api.db.campaigns.count_documents({}) == 0  # the filing step never ran
    assert events(api, run_id)[-1] == ("stop", "campaign.submit", None)
    assert api.get(f"/runs/{run_id}", headers=api.as_["marketer_national"]).json()["status"] == "stopped"


def test_audit_is_scoped_to_the_caller(api):
    reviewed = chat(api, "marketer_national", ad={**AD, "text": FIXED})
    mine = api.get(f"/audit?run_id={reviewed['run_id']}", headers=api.as_["marketer_national"]).json()
    assert [e["event"] for e in mine][:2] == ["decision", "outcome"] and mine[0]["ts"] <= mine[1]["ts"]
    assert len(api.get(f"/audit?run_id={reviewed['run_id']}", headers=api.as_["manager_national"]).json()) == len(mine)
    assert api.get(f"/audit?run_id={reviewed['run_id']}", headers=api.as_["manager_quebec"]).json() == []
    assert api.get("/audit", headers=api.as_["sales_national"]).status_code == 403

def test_authenticated_transcripts_are_private_and_timestamped(api):
    chat(api, "marketer_national", message="Hello")
    mine=api.get("/chat/t1", headers=api.as_["marketer_national"])
    assert mine.status_code == 200
    assert len(mine.json()["messages"]) == 2
    assert all(m.get("createdAt") for m in mine.json()["messages"])
    other=api.get("/chat/t1", headers=api.as_["manager_national"])
    assert other.json()["messages"] == []
    assert api.get("/chat/t1").status_code == 401


def test_repeated_assessment_reuses_models_but_checks_current_policy(api):
    body={**AD,"text":FIXED,"save":False}
    def check():
        response=api.post("/compliance/check",headers=api.as_["marketer_national"],json=body)
        assert response.status_code==200,response.text
        return response.json()
    first=check()
    assert first["tokens"]["in"]>0 and not first["cached"]
    second=check()
    assert second["cached"] and second["tokens"]["in"]==0
    api.db.fundamentals.update_one({"key":"credit.bonus_conditions"},{"$set":{"text":"A changed policy with the same version"}})
    third=check()
    assert not third["cached"] and third["tokens"]["in"]>0


def test_submission_reuses_assessment_and_stale_submission_spends_no_tokens(api,monkeypatch):
    body={**AD,"text":FIXED,"save":False}
    headers=api.as_["marketer_national"]
    first=api.post("/compliance/check",headers=headers,json=body).json()
    assert first["assessment_key"]
    def forbidden(*args,**kwargs):raise AssertionError("Submission must not call any model")
    monkeypatch.setattr(llm,"call_structured",forbidden)
    saved=api.post("/compliance/check",headers=headers,json={**body,"save":True,"assessment_key":first["assessment_key"]})
    assert saved.status_code==200,saved.text
    assert saved.json()["cached"] and saved.json()["tokens"]["in"]==0
    assert saved.json()["campaign"]["status"]=="pending_review"
    before=api.db.campaigns.count_documents({})
    api.db.fundamentals.update_one({"key":"credit.bonus_conditions"},{"$set":{"text":"Changed"}})
    stale=api.post("/compliance/check",headers=headers,json={**body,"save":True,"assessment_key":first["assessment_key"]})
    assert stale.status_code==409 and stale.json()["error"]=="stale_assessment"
    assert api.db.campaigns.count_documents({})==before
    for changes in ({"text":"changed ad"},{"channel":"social"}):
        denied=api.post("/compliance/check",headers=headers,json={**body,**changes,"save":True,"assessment_key":first["assessment_key"]})
        assert denied.status_code==409
