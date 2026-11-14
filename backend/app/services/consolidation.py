"""Consolidation: many single decisions become one standing lesson.

People do not keep every episode for ever; over time the episodes that share a pattern are distilled
into general knowledge. Here, past verdicts that turned on the same rule are grouped and one lesson
is drafted for each group, with the verdicts it came from linked to it. A draft is only a draft:
it becomes team guidance when a manager confirms it with their password.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.agent import prompts
from app.core import llm
from app.core.db import get_db
from app.models import Identity
from app.services import fundamentals, memory

MIN_EPISODES = 2
MAX_GROUPS = 4
MAX_EPISODES_SHOWN = 8


class Lesson(BaseModel):
    pattern_found: bool = Field(description="False if the decisions share no real pattern or point in different directions.")
    lesson: str = Field(description="The standing lesson, in one or two sentences. Empty if no pattern was found.")
    explanation: str = Field(description="One sentence: what the decisions have in common, or why there is no pattern.")


def groups(identity: Identity, db=None) -> list[dict]:
    """Past verdicts the caller may read, grouped by the rule they name. Largest groups first."""
    db = db if db is not None else get_db()
    at = datetime.now(timezone.utc)
    episodes = [m for m in db.memories.find({"kind": "episodic", "status": "active", "scope.team": identity.team, "scope.user_id": None}, memory.NO_VECTOR) if memory._readable(m, identity, at)]
    clauses = {c["key"]: c for c in fundamentals.list_all(identity, db) if c.get("status") == "approved"}
    already = {tuple(sorted(m.get("consolidated_from") or [])) for m in db.memories.find({"scope.team": identity.team, "status": "active", "consolidated_from": {"$exists": True}}, {"consolidated_from": 1})}
    grouped: dict[str, list[dict]] = {}
    for m in episodes:
        for key in clauses:
            if re.search(rf"(?<![\w.-]){re.escape(key)}(?![\w-])", m["text"]):
                grouped.setdefault(key, []).append(m)
    out = []
    for key, members in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        ids = tuple(sorted(str(m["_id"]) for m in members))
        if len(members) >= MIN_EPISODES and ids not in already:
            out.append({"policy_key": key, "title": clauses[key].get("title"), "episodes": members})
    return out[:MAX_GROUPS]


def draft(identity: Identity, *, usage: Optional[llm.TokenUsage] = None, run_id: Optional[str] = None, db=None) -> list[dict]:
    """One drafted lesson per group. Nothing is written."""
    proposals = []
    for group in groups(identity, db):
        shown = group["episodes"][:MAX_EPISODES_SHOWN]
        user = f"<rule key=\"{group['policy_key']}\">{group['title']}</rule>\n\n<past_decisions>\n" + "\n".join(f"- {m['text']}" for m in shown) + "\n</past_decisions>"
        lesson: Lesson = llm.call_structured(llm.fast_model(), Lesson, system=prompts.CONSOLIDATE_SYSTEM, user=user, label="consolidate", usage=usage, run_id=run_id, intent="memory_update")
        ids = [str(m["_id"]) for m in group["episodes"]]
        proposals.append({
            "policy_key": group["policy_key"], "title": group["title"], "pattern_found": lesson.pattern_found, "explanation": lesson.explanation,
            "episodes": [{"id": str(m["_id"]), "text": m["text"]} for m in shown], "episode_count": len(ids),
            # Ready for the write endpoint: the web app adds the manager's password and a reason.
            "card": {
                "target": "memory", "id": None, "kind": "procedural", "scope": {"team": identity.team, "user_id": None}, "before": None,
                "after": lesson.lesson, "action": "create", "status": "proposed", "requires_password": True, "consolidated_from": ids,
            } if lesson.pattern_found and lesson.lesson.strip() else None,
        })
    return proposals
