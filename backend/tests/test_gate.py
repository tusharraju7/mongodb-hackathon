"""The gate and ledger on an in-memory MongoDB. No network."""
import json

import mongomock
import pytest

from app.core import gate, security
from app.core.config import SEED_DIR
from app.models import Identity

MARKETER = Identity(user_id="u-marketer", email="marketer.national@tamarack.test", name="M", role="marketer", team="national")
SALES = Identity(user_id="u-sales", email="sales.national@tamarack.test", name="S", role="sales", team="national")
MANAGER = Identity(user_id="u-manager", email="manager.national@tamarack.test", name="G", role="manager", team="national")


@pytest.fixture
def db():
    database = mongomock.MongoClient().greenlight
    database.policies.insert_many(json.loads((SEED_DIR / "policies.json").read_text()))
    return database


def events(db, run_id):
    return list(db.ledger.find({"run_id": run_id}).sort("_id", 1))


def test_allowed_action_writes_decision_before_it_runs_then_outcome(db):
    seen = {}

    def action():
        seen["ledger_when_running"] = [(e["event"], e.get("decision")) for e in events(db, "r1")]
        return {"id": "ad-1"}

    result = gate.guarded(
        MARKETER, "compliance.check", {"offer_id": "TCB-FALL-2026"}, "r1", action,
        undo=lambda r: {"type": "campaign.rollback", "ref": r["id"]},
        policy_refs=[{"key": "credit.approval_claims", "version": 2}],
        summarize=lambda r: {"status": "blocked", "summary": "Blocked", "confidence": 100},
        db=db,
    )
    assert result == {"id": "ad-1"}
    assert seen["ledger_when_running"] == [("decision", "allow")]
    decision, outcome = events(db, "r1")
    assert decision["actor"] == {"user_id": "u-marketer", "email": MARKETER.email, "role": "marketer", "team": "national"}
    assert decision["auth"] == {"method": "jwt"} and decision["ts"] <= outcome["ts"]
    assert outcome["event"] == "outcome" and outcome["result"]["confidence"] == 100
    assert outcome["undo"] == {"type": "campaign.rollback", "ref": "ad-1"}
    assert outcome["policy_refs"] == [{"key": "credit.approval_claims", "version": 2}]


def test_denied_action_is_recorded_and_never_runs(db):
    called = []
    with pytest.raises(gate.Denied):
        gate.guarded(SALES, "compliance.check", {}, "r2", lambda: called.append(1), db=db)
    assert called == []
    (only,) = events(db, "r2")
    assert (only["event"], only["decision"]) == ("decision", "deny")
    assert "sales" in only["reason"] and only["actor"]["role"] == "sales"


def test_sales_holds_only_search_and_ask(db):
    for action in ("campaign.search", "campaign.ask"):
        assert gate.permitted(SALES, action, db)
    for action in ("compliance.check", "asset.regenerate", "campaign.approve", "campaign.release", "memory.write", "fundamentals.update"):
        assert not gate.permitted(SALES, action, db)
    assert not gate.permitted(MARKETER, "campaign.approve", db)
    assert not gate.permitted(MARKETER, "fundamentals.update", db)
    assert gate.permitted(MANAGER, "run.rollback", db)


def test_stop_request_halts_the_next_step_and_is_recorded(db):
    gate.open_run(MARKETER, "r3", intent="review", db=db)
    ran = []
    gate.guarded(MARKETER, "compliance.check", {}, "r3", lambda: ran.append("first"), db=db)
    assert gate.request_stop("r3", db=db)
    with pytest.raises(gate.RunStopped):
        gate.guarded(MARKETER, "campaign.submit", {}, "r3", lambda: ran.append("second"), db=db)
    assert ran == ["first"]
    assert [e["event"] for e in events(db, "r3")] == ["decision", "outcome", "stop"]
    assert db.runs.find_one({"_id": "r3"})["status"] == "stopped"
    # A stopped run stays stopped, and closing it does not overwrite that.
    with pytest.raises(gate.RunStopped):
        gate.guarded(MARKETER, "campaign.submit", {}, "r3", lambda: ran.append("third"), db=db)
    gate.close_run("r3", "completed", db=db)
    assert db.runs.find_one({"_id": "r3"})["status"] == "stopped"


def test_failed_action_records_an_error_outcome_and_re_raises(db):
    def boom():
        raise ValueError("provider down")

    with pytest.raises(ValueError):
        gate.guarded(MARKETER, "asset.regenerate", {}, "r4", boom, db=db)
    decision, outcome = events(db, "r4")
    assert outcome["result"]["status"] == "error" and "ValueError" in outcome["result"]["summary"]
    assert "undo" not in outcome


def test_secrets_and_raw_files_never_reach_the_ledger(db):
    gate.guarded(
        MANAGER, "fundamentals.update",
        {"password": "hunter2", "reason": "typo", "file": b"\x00" * 2048, "text": "x" * 1000, "nested": {"token": "abc", "keep": 1}},
        "r5", lambda: None, auth_method="jwt+password", db=db,
    )
    decision = events(db, "r5")[0]
    assert "password" not in decision["params"] and decision["params"]["nested"] == {"keep": 1}
    assert decision["params"]["file"] == "<2048 bytes>" and len(decision["params"]["text"]) == 301
    assert decision["auth"] == {"method": "jwt+password"}
    assert "hunter2" not in json.dumps(decision, default=str)


def test_step_up_and_tokens(db, monkeypatch):
    db.users.insert_one({"_id": "u-manager", "email": MANAGER.email, "name": "G", "role": "manager", "team": "national", "password_hash": security.hash_password("correct horse")})
    assert security.verify_password(MANAGER, "correct horse", db)
    assert not security.verify_password(MANAGER, "wrong", db)
    assert not security.verify_password(MANAGER, None, db)
    with pytest.raises(security.StepUpFailed):
        security.require_step_up(MANAGER, "wrong", db)
    assert security.require_step_up(MANAGER, "correct horse", db) == "jwt+password"

    assert security.authenticate(MANAGER.email.upper(), "correct horse", db).role == "manager"
    assert security.authenticate(MANAGER.email, "nope", db) is None

    monkeypatch.setattr(security, "_secret", lambda: "test-secret-that-is-long-enough-for-hs256")
    token = security.issue_token(MANAGER)
    assert security.identity_from_token(token) == MANAGER
    with pytest.raises(Exception):
        security.identity_from_token(token[:-2] + "xx")
