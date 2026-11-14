"""The chat graph: route -> one lane. An explicit LangGraph graph, not a free tool-calling agent.

The model picks the intent; code decides whether the role may act on it and what runs. No tool
schema is ever sent to a model. Conversation state (recent turns and the ad under discussion) is
kept per thread by the MongoDB checkpointer.
"""
from __future__ import annotations

from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent import lanes, prompts
from app.core import gate, llm
from app.models import Identity

HISTORY_TURNS = 6

Intent = Literal["review", "regenerate", "memory_update", "ask", "approve_release", "other"]

# The action each intent needs. Permission is checked in code against `policies`, never by the model.
INTENT_ACTION = {
    "review": "compliance.check",
    "regenerate": "asset.regenerate",
    "memory_update": "memory.write",
    "ask": "campaign.ask",
    "approve_release": "campaign.approve",
}

HELP = (
    "I can review an ad for compliance, regenerate a compliant version of a reviewed ad, update what the team's "
    "assistant knows, or answer questions about an ad. Tell me which you need."
)


class Route(BaseModel):
    intent: Intent


class ChatState(TypedDict, total=False):
    # kept across turns by the checkpointer
    history: list[dict]
    last_campaign_id: Optional[str]
    # per turn
    identity: dict
    run_id: str
    thread_id: str
    message: str
    file_id: Optional[str]
    ad: Optional[dict]
    use_memory: bool
    intent: str
    result: dict
    tokens: dict


def _usage(state: ChatState) -> llm.TokenUsage:
    u = llm.TokenUsage()
    t = state.get("tokens") or {}
    u.input, u.output = t.get("in", 0), t.get("out", 0)
    return u


def route(state: ChatState) -> dict:
    """Decide the intent. An attached file or pasted ad context is a review without asking the model."""
    ad = state.get("ad") or {}
    if state.get("file_id") or ad.get("text"):
        return {"intent": "review"}
    usage = llm.TokenUsage()
    recent = "\n".join(f"{t['role']}: {t['text'][:200]}" for t in (state.get("history") or [])[-4:]) or "(none)"
    has_ad = "yes" if state.get("last_campaign_id") or ad.get("campaign_id") else "no"
    user = f"<recent_turns>\n{recent}\n</recent_turns>\n<an_ad_is_under_discussion>{has_ad}</an_ad_is_under_discussion>\n\n<message>\n{state['message']}\n</message>"
    decided: Route = llm.call_structured(llm.fast_model(), Route, system=prompts.router_system(), user=user, label="route", usage=usage, run_id=state["run_id"], intent="route")
    return {"intent": decided.intent, "tokens": usage.as_dict()}


def _identity(state: ChatState) -> Identity:
    return Identity(**state["identity"])


def _denied(action: str, identity: Identity) -> dict:
    return {
        "reply": f"That is not something your role ({identity.role}) can do here. The request was not carried out, and the refusal has been recorded.",
        "cards": [], "memories_used": [], "status": "denied", "denied_action": action,
    }


def act(state: ChatState) -> dict:
    """Run the lane for the intent. A refusal by the gate ends the turn with a fixed reply and no further model call."""
    identity, intent, run_id = _identity(state), state.get("intent", "other"), state["run_id"]
    usage = _usage(state)
    ad = dict(state.get("ad") or {})
    campaign_id = ad.get("campaign_id") or state.get("last_campaign_id")
    try:
        # Deny before spending: a role that lacks the action is refused here, on the ledger, before
        # the lane reads a file, searches or calls a model.
        action = INTENT_ACTION.get(intent)
        if action and not gate.permitted(identity, action):
            gate.guarded(identity, action, {"via": "chat", "message": state["message"]}, run_id, lambda: None, thread_id=state.get("thread_id"))
        if intent == "review":
            text = ad.pop("text", None) or (state["message"] if not state.get("file_id") and not ad.get("campaign_id") and ad.get("offer_id") else None)
            if not text and not state.get("file_id") and not ad.get("campaign_id") and state.get("last_campaign_id"):
                ad["campaign_id"] = state["last_campaign_id"]
            result = lanes.review_lane(identity, run_id, text=text, file_id=state.get("file_id"), ctx=ad, use_memory=state.get("use_memory", True), usage=usage, thread_id=state.get("thread_id"))
        elif intent == "regenerate":
            if not campaign_id:
                result = {"reply": "Tell me which ad to regenerate, or review one first.", "cards": [], "memories_used": [], "status": "needs_input"}
            else:
                out = lanes.regenerate_lane(identity, run_id, campaign_id=campaign_id, usage=usage, thread_id=state.get("thread_id"))
                cards = [{"type": "compliance_report", "data": out["report"]}] + ([{"type": "campaign", "data": out["campaign"]}] if out.get("campaign") else [])
                result = {"reply": out["reply"], "cards": cards, "memories_used": [], "status": "completed" if out["status"] == "regenerated" else "blocked", "campaign_id": campaign_id}
        elif intent == "memory_update":
            result = lanes.memory_update_lane(identity, run_id, message=state["message"], usage=usage, thread_id=state.get("thread_id"))
        elif intent == "ask":
            result = lanes.ask_lane(identity, run_id, question=state["message"], thread_campaign_id=campaign_id, usage=usage, thread_id=state.get("thread_id"))
        elif intent == "approve_release":
            # Not a chat action. The gate still records a refusal for a role that may not approve.
            gate.guarded(identity, "campaign.approve", {"via": "chat", "message": state["message"]}, run_id, lambda: None, thread_id=state.get("thread_id"), summarize=lambda _: {"status": "ok", "summary": "Pointed to the library; nothing changed"})
            result = {"reply": "Approving and releasing are done from the ad library, with the Approve and Release buttons, so each one is a deliberate click.", "cards": [], "memories_used": [], "status": "completed"}
        else:
            result = {"reply": HELP, "cards": [], "memories_used": [], "status": "completed"}
    except gate.Denied:
        result = _denied(INTENT_ACTION.get(intent, intent), identity)
    except gate.RunStopped:
        result = {"reply": "This run was stopped. The step that was about to start did not run.", "cards": [], "memories_used": [], "status": "stopped"}

    history = (state.get("history") or []) + [{"role": "user", "text": state["message"], "createdAt": datetime.now(timezone.utc).isoformat()}, {"role": "assistant", "text": result["reply"], "createdAt": datetime.now(timezone.utc).isoformat()}]
    update: dict[str, Any] = {"result": result, "tokens": usage.as_dict(), "history": history[-HISTORY_TURNS * 2 :]}
    if result.get("campaign_id"):
        update["last_campaign_id"] = result["campaign_id"]
    return update


def build(checkpointer=None):
    g = StateGraph(ChatState)
    g.add_node("route", route)
    g.add_node("act", act)
    g.add_edge(START, "route")
    g.add_edge("route", "act")
    g.add_edge("act", END)
    return g.compile(checkpointer=checkpointer)


@lru_cache
def chat_graph():
    """The graph with conversation state kept in MongoDB (collections `checkpoints`, `checkpoint_writes`)."""
    from langgraph.checkpoint.mongodb import MongoDBSaver

    from app.core.config import get_settings
    from app.core.db import get_client

    return build(MongoDBSaver(get_client(), db_name=get_settings().mongodb_db))


def run_turn(identity: Identity, *, thread_id: str, run_id: str, message: str, file_id: Optional[str] = None, ad: Optional[dict] = None, use_memory: bool = True, graph=None) -> dict:
    graph = graph or chat_graph()
    state = graph.invoke(
        {"identity": identity.model_dump(), "run_id": run_id, "thread_id": thread_id, "message": message, "file_id": file_id, "ad": ad, "use_memory": use_memory, "intent": "", "result": {}, "tokens": {}},
        # A thread belongs to one user: the id is namespaced so nobody can read another person's conversation.
        config={"configurable": {"thread_id": f"{identity.user_id}:{thread_id}"}, "run_name": "chat_turn", "metadata": {"run_id": run_id, "role": identity.role, "team": identity.team}},
    )
    result = dict(state["result"])
    result.update({"intent": state.get("intent"), "tokens": state.get("tokens") or {"in": 0, "out": 0}, "run_id": run_id})
    return result

def read_history(identity: Identity, thread_id: str, graph=None) -> list[dict]:
    graph = graph or chat_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": f"{identity.user_id}:{thread_id}"}})
    return (snapshot.values or {}).get("history", [])
