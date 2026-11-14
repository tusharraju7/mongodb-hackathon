"""The agent: the model chooses its next step, and the gate decides whether it may take it.

The rest of the backend is a fixed flow: code decides the steps and the model fills them in. Here
the model is given a goal and a handful of tools, and it decides which to call and in what order,
until it replies. What it is allowed to do is not up to it:

  - every turn is itself a gated step (`agent.run`): identity re-read, run budget, stop flag;
  - every tool is a lane or a service that already goes through `guarded()`, acting as the agent,
    so the five checks apply to each call and an approval or release is always refused;
  - a refusal comes back to the model as the tool's result, so it has to work with it;
  - verdicts, routes and confidence are still computed in code inside the tools.

Each turn's steps are checkpointed under their own prefix (`t3-review`, `t4-file` ...), so a
lane called twice in one run does not reuse the first call's result.
"""
from __future__ import annotations

import inspect
import json
import os
import time
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent import lanes, prompts
from app.core import gate, llm
from app.core.db import get_db
from app.models import Identity
from app.services import campaigns, fundamentals, memory

MAX_TURNS = 8
MAX_RESULT_CHARS = 4000


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description, "input_schema": {"type": "object", "properties": properties, "required": required}}


ID = {"type": "string", "description": "The ad's id, exactly as a tool returned it."}
TOOLS = [
    _tool("find_ad", "Find ads in the team's library by name or description. Returns up to five, with id, name, version, status and last decision.",
          {"query": {"type": "string", "description": "Words from the ad's name or what it is about."}}, ["query"]),
    _tool("review_ad", "Review a library ad. Returns the decision, each finding with what it rests on, and whether a corrected version is available.",
          {"campaign_id": ID}, ["campaign_id"]),
    _tool("review_text", "Review ad copy the colleague pasted, and file it in the library as a new ad.",
          {"text": {"type": "string"}, "name": {"type": "string"}, "channel": {"type": "string", "description": "Where it will run, e.g. 'Instagram (paid social)'."}}, ["text", "name", "channel"]),
    _tool("get_policy", "Read the full text of a regulation by its key, e.g. REG-03.", {"key": {"type": "string"}}, ["key"]),
    _tool("recall_memory", "Search the team's binding decisions, guidance and past verdicts.", {"query": {"type": "string"}}, ["query"]),
    _tool("regenerate_ad", "Update a reviewed ad that needs changes: produce its next version with the corrections applied. The copy is re-reviewed before anything is saved. With voice=true an ElevenLabs voice-over of the corrected copy is recorded too.",
          {"campaign_id": ID, "voice": {"type": "boolean", "description": "Also record a voice-over with ElevenLabs. Default true."}}, ["campaign_id"]),
    _tool("approve_ad", "Approve an ad for release. Approval belongs to a person: the system will refuse you. Use only when the colleague explicitly asks.", {"campaign_id": ID}, ["campaign_id"]),
    _tool("release_ad", "Release an approved ad. Release belongs to a person: the system will refuse you. Use only when the colleague explicitly asks.", {"campaign_id": ID}, ["campaign_id"]),
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def model():
    """The fast model by default; AGENT_MODEL=main uses the verdict model for the loop as well."""
    return llm.main_model() if os.environ.get("AGENT_MODEL", "fast") == "main" else llm.fast_model()


def invoke(messages: list) -> AIMessage:
    """One turn of the loop. Replaced in the offline tests by a scripted model."""
    return model().bind_tools(TOOLS).invoke(messages, config={"run_name": "agent_turn", "tags": ["greenlight", "agent"]})


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


# ---------------------------------------------------------------- what each tool returns to the model
# Summaries, not documents: the model gets what it needs to decide the next step and to explain.


def _report_brief(report: dict) -> dict:
    findings = []
    for v in report.get("violations", []):
        findings.append({
            "rests_on": v.get("fundamental_key") or f"internal decision ({v.get('source_label') or 'team memory'})",
            "materiality": v.get("materiality"), "quote": v.get("quote"), "problem": v.get("explanation"), "fix": v.get("fix"),
            "certainty": v.get("certainty"),
        })
    return {
        "decision": report.get("decision") or report.get("verdict"), "verdict": report.get("verdict"), "route": report.get("route"),
        "confidence": (report.get("confidence") or {}).get("score"), "summary": report.get("summary"), "findings": findings,
        "conflicts": [{"between": [b["label"] for b in c["between"]], "winner": c["winner"]["label"], "why": c["explanation"]} for c in report.get("conflicts", [])],
        "corrected_version_available": bool(report.get("corrected_copy")), "missing_inputs": report.get("missing_inputs") or [],
        "flaws_marked_on_image": report.get("annotated_url"),
    }


def _ad_brief(card: dict) -> dict:
    return {
        "id": card["id"], "name": card.get("name"), "version": card.get("version"), "status": card.get("status"), "form": card.get("modality"),
        "channel": card.get("channel"), "last_decision": card.get("compliance_verdict"), "text": (card.get("text") or "")[:600],
        "asset_url": (card.get("asset") or {}).get("url"), "voiceover_url": (card.get("voiceover") or {}).get("url"),
    }


class _Run:
    """What the loop knows while it runs: who, which run, and the latest ad and report it touched."""

    def __init__(self, identity: Identity, run_id: str, usage: llm.TokenUsage, db):
        self.identity, self.run_id, self.usage, self.db = identity, run_id, usage, db
        self.ad: Optional[dict] = None
        self.report: Optional[dict] = None
        self.turn = 0

    # -- tools

    def find_ad(self, query: str) -> dict:
        def search() -> list[dict]:
            ads = campaigns.list_for(self.identity, db=self.db)
            words = [w for w in query.lower().replace("'", " ").split() if len(w) > 2]
            scored = sorted(((sum(w in f"{a.get('name') or ''} {a.get('summary') or ''}".lower() for w in words), a) for a in ads), key=lambda x: -x[0])
            hits = [a for score, a in scored if score > 0][:5]
            # Names first, which needs no embedding; meaning only when no name matches.
            return hits or campaigns.search(self.identity, query, k=3, db=self.db)

        hits = gate.guarded(self.identity, "campaign.search", {"q": query, "via": "agent"}, self.run_id, search, db=self.db,
                            summarize=lambda h: {"status": "ok", "summary": f"{len(h)} ad(s) matched"})
        return {"ads": [_ad_brief(a) for a in hits]}

    def review_ad(self, campaign_id: str) -> dict:
        out = lanes.review_lane(self.identity, self.run_id, text=None, file_id=None, ctx={"campaign_id": campaign_id}, usage=self.usage, save=True, db=self.db)
        return self._reviewed(out)

    def review_text(self, text: str, name: str, channel: str) -> dict:
        out = lanes.review_lane(self.identity, self.run_id, text=text, file_id=None, ctx={"name": name, "channel": channel}, usage=self.usage, save=True, db=self.db)
        return self._reviewed(out)

    def _reviewed(self, out: dict) -> dict:
        report = next((c["data"] for c in out["cards"] if c["type"] == "compliance_report"), None)
        card = next((c["data"] for c in out["cards"] if c["type"] == "campaign"), None)
        self.report, self.ad = report or self.report, card or self.ad
        return {"ad": _ad_brief(card) if card else None, "review": _report_brief(report) if report else None, "note": out["reply"] if not report else None}

    def get_policy(self, key: str) -> dict:
        clause = gate.guarded(self.identity, "fundamentals.read", {"key": key}, self.run_id, lambda: fundamentals.get(key, self.db), db=self.db,
                              summarize=lambda c: {"status": "ok", "summary": f"Read {c['key']} version {c.get('version', 1)}"})
        return {"key": clause["key"], "title": clause.get("title"), "version": clause.get("version", 1), "text": clause["text"][:1500]}

    def recall_memory(self, query: str) -> dict:
        found = gate.guarded(self.identity, "memory.read", {"q": query}, self.run_id,
                             lambda: memory.recall(self.identity, query, kinds=["procedural", "semantic", "episodic"], k=4, db=self.db), db=self.db,
                             summarize=lambda m: {"status": "ok", "summary": f"{len(m)} memories in scope"})
        return {"memories": found}

    def regenerate_ad(self, campaign_id: str, voice: bool = True) -> dict:
        out = lanes.regenerate_lane(self.identity, self.run_id, campaign_id=campaign_id, usage=self.usage, voice=voice, db=self.db)
        if out.get("campaign"):
            self.ad = out["campaign"]
        self.report = out.get("report") or self.report
        return {
            "status": out["status"], "attempts": out.get("attempts"), "message": out["reply"],
            "new_version": _ad_brief(out["campaign"]) if out.get("campaign") and out["status"] == "regenerated" else None,
            "review_of_new_version": _report_brief(out["report"]) if out.get("report") else None,
        }

    def approve_ad(self, campaign_id: str) -> dict:
        card = campaigns.card(campaigns.approve(self.identity, self.run_id, campaign_id, db=self.db))
        self.ad = card
        return {"ad": _ad_brief(card)}

    def release_ad(self, campaign_id: str) -> dict:
        card = campaigns.card(campaigns.release(self.identity, self.run_id, campaign_id, db=self.db))
        self.ad = card
        return {"ad": _ad_brief(card)}

    # -- one call

    def call(self, name: str, args: dict) -> tuple[str, dict]:
        """Run one tool. Returns (status, result for the model). A refusal is a result, not a crash."""
        if name not in TOOL_NAMES:
            return "error", {"error": f"There is no tool called {name}."}
        fn: Callable[..., dict] = getattr(self, name)
        try:
            inspect.signature(fn).bind(**args)  # a wrong input is the model's mistake, reported back to it
        except TypeError as wrong:
            return "error", {"error": f"Wrong input for {name}: {wrong}"}
        try:
            with gate.step_scope(f"t{self.turn}-"):
                return "ok", fn(**args)
        except gate.Denied as refusal:
            return "refused", {"refused": True, "decided_by": refusal.check, "reason": str(refusal)}
        except campaigns.NotApprovable as refusal:
            return "refused", {"refused": True, "decided_by": "state", "reason": str(refusal)}
        except campaigns.StaleApproval as refusal:
            return "refused", {"refused": True, "decided_by": "state", "reason": str(refusal), "changes": refusal.changes}
        except (campaigns.NotFound, fundamentals.NotFound) as missing:
            return "error", {"error": str(missing) or "Not found in your scope."}


def run_agent(identity: Identity, run_id: str, goal: str, *, campaign_id: Optional[str] = None, max_turns: int = MAX_TURNS, usage: Optional[llm.TokenUsage] = None, db=None) -> dict:
    db = db if db is not None else get_db()
    usage = usage or llm.TokenUsage()
    state = _Run(identity, run_id, usage, db)
    ask = goal + (f"\n\n(The ad this is about has id {campaign_id}.)" if campaign_id else "")
    messages: list[Any] = [SystemMessage(content=prompts.agent_system()), HumanMessage(content=ask)]
    steps: list[dict] = []
    reply, status = "", "completed"

    with gate.acting_as("agent"):
        for turn in range(1, max(1, min(max_turns, 12)) + 1):
            state.turn = turn

            def think() -> AIMessage:
                started = time.time()
                answer = invoke(messages)
                meta = getattr(answer, "usage_metadata", None) or {}
                usage.add("agent_turn", meta)
                spent = {"in": int(meta.get("input_tokens", 0)), "out": int(meta.get("output_tokens", 0))}
                gate.emit("model_call", "model.agent_turn", duration_ms=int((time.time() - started) * 1000), tokens=spent,
                          params={"turn": turn, "prompt_version": prompts.PROMPT_VERSION, "tools_offered": len(TOOLS), "output_hash": gate.digest(answer.content)},
                          result={"status": "ok", "summary": f"chose {', '.join(c['name'] for c in answer.tool_calls) or 'to reply'}"})
                gate.count(model_calls=1, tokens=spent["in"] + spent["out"])
                return answer

            try:
                answer: AIMessage = gate.guarded(
                    identity, "agent.run", {"turn": turn, "goal": goal}, run_id, think, db=db,
                    summarize=lambda a: {"status": "ok", "summary": "Called " + ", ".join(c["name"] for c in a.tool_calls) if a.tool_calls else "Replied"},
                )
            except gate.Denied as refusal:
                reply, status = (f"The agent stopped: {refusal}" if turn > 1 else "That is not something your role can do here. The refusal has been recorded."), "denied"
                break
            except gate.RunStopped:
                reply, status = "This run was stopped. The step that was about to start did not run.", "stopped"
                break

            messages.append(answer)
            if not answer.tool_calls:
                reply = _text(answer)
                break
            for call in answer.tool_calls:
                try:
                    outcome, result = state.call(call["name"], dict(call.get("args") or {}))
                except gate.RunStopped:
                    outcome, result = "stopped", {"stopped": True}
                body = json.dumps(result, default=str)[:MAX_RESULT_CHARS]
                messages.append(ToolMessage(content=body, tool_call_id=call["id"]))
                summary = result.get("reason") or result.get("error") or result.get("message") or (result.get("review") or {}).get("decision") or outcome
                gate.record(identity, run_id, "tool_call", f"tool.{call['name']}", db=db,
                            params={"turn": turn, "tool": call["name"], "input": gate.redact(call.get("args") or {})},
                            result={"status": outcome, "summary": str(summary)[:300]}, decided_by=result.get("decided_by"))
                steps.append({"turn": turn, "tool": call["name"], "input": call.get("args") or {}, "status": outcome, "summary": str(summary)[:300]})
                if outcome == "stopped":
                    status = "stopped"
            if status == "stopped":
                reply = "This run was stopped. The step that was about to start did not run."
                break
        else:
            reply = reply or f"I stopped after {len(steps)} steps without finishing. What I did is listed below; a person should take it from here."
            status = "incomplete"

    return {
        "reply": reply, "status": status, "steps": steps, "turns": state.turn,
        "campaign": state.ad, "report": state.report, "voiceover_url": ((state.ad or {}).get("voiceover") or {}).get("url"),
    }
