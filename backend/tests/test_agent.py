"""The agent loop, offline: a scripted model picks the tools; the real gate, lanes and services run."""
import json
import uuid
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from langchain_core.messages import AIMessage, ToolMessage

from app.agent import agent_loop
from app.core import gate
from app.services import media
from tests.test_api_flow import AD, FIXED, RUNNING, api, card, chat  # noqa: F401  (api is a fixture)


@pytest.fixture(autouse=True)
def files(api, monkeypatch):
    """GridFS does not run on the in-memory database: files go in a dict, their records in `fs.files`."""
    data = {}

    def store(content, mime, filename="upload", db=None, metadata=None):
        file_id = api.db["fs.files"].insert_one({"filename": filename, "length": len(content), "uploadDate": datetime.now(timezone.utc), "metadata": {"mime": mime, **(metadata or {})}}).inserted_id
        data[str(file_id)] = content
        return str(file_id)

    def delete(file_id, db=None):
        api.db["fs.files"].delete_one({"_id": ObjectId(file_id)})
        data.pop(str(file_id), None)

    monkeypatch.setattr(media, "store", store)
    monkeypatch.setattr(media, "delete", delete)
    return data


def scripted(plan):
    """A stand-in model. `plan` is a list of functions from the last tool result to the next message."""
    turns = iter(plan)

    def invoke(messages):
        last = next((json.loads(m.content) for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        return next(turns)(last)

    return invoke


def tool(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}", "type": "tool_call"}], usage_metadata={"input_tokens": 500, "output_tokens": 40, "total_tokens": 540})


def say(text):
    return AIMessage(content=text, usage_metadata={"input_tokens": 600, "output_tokens": 80, "total_tokens": 680})


def test_the_agent_reviews_updates_the_ad_with_a_voice_over_and_is_refused_approval(api, monkeypatch):
    spoken = []
    monkeypatch.setattr(media, "synthesize_bytes", lambda text, language="en": spoken.append(text) or b"ID3 fake mp3")
    ad = card(chat(api, "marketer_national", ad={**AD, "text": RUNNING, "name": "Fall cashback email"}), "campaign")

    seen = {}
    monkeypatch.setattr(agent_loop, "invoke", scripted([
        lambda _: tool("find_ad", query="fall cashback email"),
        lambda found: seen.setdefault("found", found) and tool("review_ad", campaign_id=found["ads"][0]["id"]),
        lambda reviewed: seen.setdefault("reviewed", reviewed) and tool("regenerate_ad", campaign_id=ad["id"], voice=True),
        lambda regenerated: seen.setdefault("regenerated", regenerated) and tool("approve_ad", campaign_id=ad["id"]),
        lambda refused: seen.setdefault("refused", refused) and say("Version 2 passes. Approval is yours: use the Approve button."),
    ]))
    r = api.post("/agent", headers=api.as_["manager_national"], json={"goal": "Fix the fall cashback email and approve it."})
    assert r.status_code == 200, r.text
    out = r.json()

    # It found the ad, reviewed it, and saw what the review found and that a correction exists.
    assert seen["found"]["ads"][0]["id"] == ad["id"]
    review = seen["reviewed"]["review"]
    assert (review["verdict"], review["decision"]) == ("blocked", "rejected") and review["corrected_version_available"] is True
    assert "credit.approval_claims" in {f["rests_on"] for f in review["findings"]}

    # It updated the ad: version 2, passing, with an ElevenLabs voice-over of the corrected copy only.
    assert seen["regenerated"]["status"] == "regenerated" and seen["regenerated"]["review_of_new_version"]["verdict"] == "pass"
    assert spoken == [FIXED]
    assert (out["campaign"]["version"], out["campaign"]["source"], out["campaign"]["text"]) == (2, "regenerated", FIXED)
    assert out["voiceover_url"] and out["voiceover_url"] == out["campaign"]["voiceover"]["url"]

    # It tried to approve, for a manager who may approve, and the gate refused the agent.
    assert seen["refused"] == {"refused": True, "decided_by": "initiator", "reason": seen["refused"]["reason"]}
    stored = api.db.campaigns.find_one({})
    assert stored["status"] == "pending_review" and "approval" not in stored

    assert out["status"] == "completed" and out["turns"] == 5 and out["reply"].startswith("Version 2 passes")
    assert [(s["tool"], s["status"]) for s in out["steps"]] == [("find_ad", "ok"), ("review_ad", "ok"), ("regenerate_ad", "ok"), ("approve_ad", "refused")]

    # The ledger: each turn authorised before the model was asked, each tool call recorded, the chain intact.
    run_id = out["run_id"]
    turns = list(api.db.ledger.find({"run_id": run_id, "event": "decision", "action": "agent.run"}))
    assert len(turns) == 5 and all(t["decision"] == "allow" and t["initiator"] == "agent" for t in turns)
    calls = [(e["action"], e["result"]["status"]) for e in api.db.ledger.find({"run_id": run_id, "event": "tool_call"}).sort("seq", 1)]
    assert calls == [("tool.find_ad", "ok"), ("tool.review_ad", "ok"), ("tool.regenerate_ad", "ok"), ("tool.approve_ad", "refused")]
    denial = api.db.ledger.find_one({"run_id": run_id, "event": "decision", "action": "campaign.approve"})
    assert (denial["decision"], denial["decided_by"]) == ("deny", "initiator")
    assert gate.verify_chain(run_id, api.db)["intact"] is True
    # Each turn's steps were checkpointed apart: the review in turn 2 and the one inside regenerate did not collide.
    steps = api.db.runs.find_one({"_id": run_id})["steps"]
    assert {"t2-review", "t3-copy", "t3-file", "t3-voiceover"} <= set(steps)

    # Rolling the run back undoes the new version and removes the voice-over.
    rolled = api.post(f"/runs/{run_id}/rollback", headers=api.as_["manager_national"]).json()
    assert rolled["status"] == "rolled_back" and api.db.campaigns.find_one({})["version"] == 1
    assert not media.run_files(run_id, "voiceover", api.db)


def test_a_role_that_may_not_run_the_agent_is_refused_before_any_model_call(api, monkeypatch):
    called = []
    monkeypatch.setattr(agent_loop, "invoke", lambda messages: called.append(1) or say("hi"))
    out = api.post("/agent", headers=api.as_["sales_national"], json={"goal": "Fix every ad."}).json()
    assert out["status"] == "denied" and called == [] and out["steps"] == []
    (refusal,) = api.db.ledger.find({"run_id": out["run_id"]})
    assert (refusal["action"], refusal["decision"], refusal["decided_by"]) == ("agent.run", "deny", "role")


def test_a_wrong_tool_input_goes_back_to_the_model_and_the_loop_is_capped(api, monkeypatch):
    monkeypatch.setattr(agent_loop, "invoke", lambda messages: tool("get_policy", clause="x"))
    out = api.post("/agent", headers=api.as_["marketer_national"], json={"goal": "Loop for ever.", "max_turns": 3}).json()
    assert out["status"] == "incomplete" and out["turns"] == 3
    assert all(s["status"] == "error" and "Wrong input" in s["summary"] for s in out["steps"])


def test_the_agent_leaves_an_ad_that_passes_unchanged(api, monkeypatch):
    ad = card(chat(api, "marketer_national", ad={**AD, "text": FIXED, "name": "Clean ad"}), "campaign")
    monkeypatch.setattr(agent_loop, "invoke", scripted([
        lambda _: tool("review_ad", campaign_id=ad["id"]),
        lambda reviewed: say("It passes; nothing to change.") if reviewed["review"]["verdict"] == "pass" else tool("regenerate_ad", campaign_id=ad["id"]),
    ]))
    out = api.post("/agent", headers=api.as_["marketer_national"], json={"goal": "Check the clean ad and fix it if needed."}).json()
    assert out["reply"] == "It passes; nothing to change." and api.db.campaigns.find_one({})["version"] == 1
