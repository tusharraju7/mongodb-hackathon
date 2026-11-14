"""The four lanes a request can take. Each step with a side effect is its own gated action,
so a stop request takes effect between steps and every step is on the ledger.

Replies are assembled in code from the results. The model is called only where the docs say:
claim extraction, image reading, the verdict, one copy repair, drafting a change, answering.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.agent import prompts
from app.core import embeddings, gate, llm
from app.core.db import get_db
from app.models import ComplianceReport, Grounding, Identity
from app.services import campaigns, compliance, fundamentals, media, memory, offers
from app.services.compliance import Sources, default_sources

EPISODIC_TTL_DAYS = 30


def _report_outcome(r: compliance.ReviewResult) -> dict:
    rep = r.report
    status = "ok" if rep.verdict == "pass" else "blocked"
    return {"status": status, "summary": f"{rep.verdict}: {rep.route_reason}", "confidence": rep.confidence.score}


def _episodic_text(identity: Identity, ctx: dict, report: ComplianceReport, name: Optional[str]) -> str:
    """The agent's own record of a verdict, written in code so it states only what the report states."""
    head = f"A {identity.team} {ctx.get('channel', '')} ad for {ctx.get('offer_id')}".replace("  ", " ")
    if name:
        head += f" ('{name}')"
    if report.verdict == "pass":
        return f"{head} passed review."
    points = []
    for v in report.violations[:4]:
        ref = v.fundamental_key or "a team instruction"
        points.append(f"{ref} ({v.quote})" if v.quote else ref)
    return f"{head} was {report.verdict.replace('_', ' ')} for: {'; '.join(points)}. Route: {report.route.replace('_', ' ')}."


# ---------------------------------------------------------------- review


def review_lane(
    identity: Identity, run_id: str, *, text: Optional[str], file_id: Optional[str], ctx: dict, use_memory: bool = True,
    usage: Optional[llm.TokenUsage] = None, thread_id: Optional[str] = None, save: bool = True,
    sources: Optional[Sources] = None, db=None,
) -> dict:
    db = db if db is not None else get_db()
    sources = sources or default_sources()
    usage = usage or llm.TokenUsage()
    ctx = {**ctx, "team": identity.team}
    modality, mime = "text", None
    existing = None

    # An ad already in the library: review its stored text; nothing is read again.
    if ctx.get("campaign_id") and not text and not file_id:
        existing = campaigns.get(identity, ctx["campaign_id"], db)
        text, modality = existing["text"], existing.get("modality", "text")
        # The stored ad's own context rules; a form default must not turn a Quebec ad into a national one.
        for key in ("product", "offer_id", "region", "channel", "language", "budget", "visual_notes"):
            ctx[key] = existing.get(key) or ctx.get(key)
        ctx["name"] = ctx.get("name") or existing.get("name")

    # A file is turned into text once. The file itself is never sent to a model again.
    if file_id:
        data, mime = media.open_file(file_id, db)
        modality = media.kind_of(mime)
        if modality == "audio":
            text = gate.guarded(
                identity, "compliance.check", {"step": "transcribe", "file_id": file_id, "bytes": len(data)}, run_id,
                lambda: media.transcribe_bytes(data), thread_id=thread_id, db=db,
                summarize=lambda t: {"status": "ok", "summary": f"Transcribed {len(t.split())} words from audio"},
            )
        else:
            reading = gate.guarded(
                identity, "compliance.check", {"step": "read_image", "file_id": file_id, "bytes": len(data)}, run_id,
                lambda: media.read_image_bytes(data, mime, usage=usage, run_id=run_id), thread_id=thread_id, db=db,
                summarize=lambda r: {"status": "ok", "summary": f"Read {len(r['text'].split())} words from the image"},
            )
            text = reading["text"]
            ctx["visual_notes"] = reading["visual_notes"]
            ctx["fine_print_legible"] = reading["fine_print_legible"]
    ctx["modality"] = modality

    if not (text or "").strip():
        return {"reply": "There is no ad text to review. Paste the copy, attach an audio or image file, or choose an ad from the library.", "cards": [], "memories_used": [], "status": "needs_input"}

    result: compliance.ReviewResult = gate.guarded(
        identity, "compliance.check",
        {"step": "review", "modality": modality, "offer_id": ctx.get("offer_id"), "region": ctx.get("region"), "channel": ctx.get("channel"), "text": text},
        run_id, lambda: compliance.review(text, ctx, identity, run_id, use_memory=use_memory, sources=sources, usage=usage),
        thread_id=thread_id, db=db,
        policy_refs=lambda r: r.report.checked_fundamentals, memories_used=lambda r: r.report.memories_used,
        summarize=_report_outcome, tokens=usage.as_dict,
    )
    report = result.report
    cards = [{"type": "compliance_report", "data": report.model_dump()}]
    chips = _memory_chips(report.memories_used, db)

    if report.missing_inputs:
        return {"reply": report.summary, "cards": cards, "memories_used": chips, "status": "needs_input"}

    reply = report.summary
    campaign = None
    if save:
        ex = result.extraction
        ctx["language"] = ctx.get("language") or ex.language
        episodic = _episodic_text(identity, ctx, report, ctx.get("name"))
        # One embedding request covers the ad's search text and the memory of this verdict.
        ad_vector, memory_vector = embeddings.embed_documents([campaigns.search_document(ex.description, ex.summary), episodic])
        campaign = campaigns.submit(
            identity, run_id, name=ctx.get("name"), text=text, ctx=ctx, facts=ex.facts().model_dump(), summary=ex.summary,
            description=ex.description, modality=modality, file_id=file_id or _first_asset(existing), mime=mime or _first_mime(existing),
            compliance=report, cache_key=result.cache_key, campaign_id=ctx.get("campaign_id"), vector=ad_vector, db=db,
        ) if not existing or existing.get("text") != text else _refresh_report(existing, report, result.cache_key, db)
        if report.verdict != "pass" and use_memory:
            memory.remember(
                identity, run_id, kind="episodic", text=episodic, scope={"team": identity.team, "user_id": None},
                ttl_days=EPISODIC_TTL_DAYS, source_type="agent", vector=memory_vector, db=db,
            )
        cards.append({"type": "campaign", "data": campaigns.card(campaign)})

    if report.verdict == "pass":
        reply += " It is filed as pending review and needs a manager's approval before release." if save else ""
    else:
        reply += f" Next step: {report.route.replace('_', ' ')}." + (" You can regenerate a compliant version." if report.corrected_copy else "")
    return {"reply": reply, "cards": cards, "memories_used": chips, "status": "completed", "campaign_id": str(campaign["_id"]) if campaign else None}


def _first_asset(existing: Optional[dict]) -> Optional[str]:
    assets = (existing or {}).get("assets") or []
    return assets[0]["file_id"] if assets else None


def _first_mime(existing: Optional[dict]) -> Optional[str]:
    assets = (existing or {}).get("assets") or []
    return assets[0].get("mime") if assets else None


def _refresh_report(existing: dict, report: ComplianceReport, cache_key: Optional[str], db) -> dict:
    """Re-reviewing an unchanged library ad updates its report in place; it is not a new version.

    A re-review that no longer passes withdraws any approval, so a stale verdict can never be released.
    """
    from datetime import datetime, timezone

    update: dict = {"$set": {"compliance": {**report.model_dump(), "checked_at": datetime.now(timezone.utc), "cache_key": cache_key}}}
    if report.verdict != "pass" and existing.get("status") in ("approved", "pending_review"):
        update["$set"]["status"] = "pending_review"
        update["$unset"] = {"approval": ""}
    db.campaigns.update_one({"_id": existing["_id"]}, update)
    return db.campaigns.find_one({"_id": existing["_id"]}, {"embedding": 0})


def _memory_chips(ids: list[str], db) -> list[dict]:
    from app.core.db import oid

    if not ids:
        return []
    found = {str(m["_id"]): m for m in db.memories.find({"_id": {"$in": [oid(i) for i in ids]}}, {"kind": 1, "text": 1})}
    return [{"id": i, "kind": found[i]["kind"], "text": found[i]["text"]} for i in ids if i in found]


# ---------------------------------------------------------------- regenerate


def regenerate_lane(identity: Identity, run_id: str, *, campaign_id: str, usage: Optional[llm.TokenUsage] = None, thread_id: Optional[str] = None, sources: Optional[Sources] = None, db=None) -> dict:
    """Produce the next version of an ad that passes the same review, in the ad's own form. Fails closed."""
    db = db if db is not None else get_db()
    sources = sources or default_sources()
    usage = usage or llm.TokenUsage()
    ad = campaigns.get(identity, campaign_id, db)
    report = ComplianceReport(**{k: v for k, v in (ad.get("compliance") or {}).items() if k in ComplianceReport.model_fields})
    params = {"campaign_id": campaign_id, "from_version": ad.get("version", 1), "modality": ad.get("modality", "text")}

    if report.verdict == "pass":
        gate.guarded(identity, "asset.regenerate", params, run_id, lambda: None, thread_id=thread_id, db=db, summarize=lambda _: {"status": "ok", "summary": "Nothing to regenerate: the ad already passes"})
        return {"status": "failed", "campaign": campaigns.card(ad), "report": report.model_dump(), "attempts": 0, "reply": "This ad already passes review, so there is nothing to regenerate."}

    ctx = {k: ad.get(k) for k in ("product", "offer_id", "region", "channel", "language", "budget")}
    ctx["team"] = identity.team

    # 1. Copy first. Nothing is rendered until the copy has passed.
    outcome: compliance.RegeneratedCopy = gate.guarded(
        identity, "asset.regenerate", {**params, "step": "copy"}, run_id,
        lambda: compliance.regenerate_copy(ad["text"], report, ctx, identity, run_id, sources=sources, usage=usage),
        thread_id=thread_id, db=db, tokens=usage.as_dict,
        policy_refs=lambda o: o.review.report.checked_fundamentals,
        summarize=lambda o: {"status": "ok" if o.status == "regenerated" else "blocked", "summary": f"Corrected copy {'passed' if o.status == 'regenerated' else 'did not pass'} review after {o.attempts} attempt(s)", "confidence": o.review.report.confidence.score},
    )
    if outcome.status != "regenerated":
        return {
            "status": "failed", "campaign": None, "report": outcome.review.report.model_dump(), "attempts": outcome.attempts,
            "reply": "A compliant version could not be produced automatically. Nothing was rendered or saved; the remaining findings need a person.",
        }

    passing = outcome.review.report
    language = report.corrected_language or ad.get("language") or "en"
    modality = ad.get("modality", "text")
    ctx["language"] = language

    # 2. Render in the ad's own form. A new recording or a new rendering, not an edit of the original.
    file_id = mime = None
    if modality == "audio":
        file_id, mime = gate.guarded(
            identity, "asset.regenerate", {**params, "step": "render_audio", "language": language}, run_id,
            lambda: (media.synthesize_speech(outcome.copy, language, db), "audio/mpeg"), thread_id=thread_id, db=db,
            summarize=lambda r: {"status": "ok", "summary": "Recorded the corrected script with a stock voice", "ref": {"collection": "fs.files", "id": r[0]}},
        )
    elif modality == "image":
        file_id, mime = gate.guarded(
            identity, "asset.regenerate", {**params, "step": "render_image", "language": language}, run_id,
            lambda: (media.render_image(outcome.copy, language=language, offer=outcome.review.offer, db=db), "image/png"), thread_id=thread_id, db=db,
            summarize=lambda r: {"status": "ok", "summary": "Rendered the corrected copy on the brand template", "ref": {"collection": "fs.files", "id": r[0]}},
        )

    # 3. File it as the next version, with the passing report. It still needs approval.
    ex = outcome.review.extraction
    episodic = f"The corrected version of the {identity.team} {ad.get('channel')} ad '{ad.get('name')}' for {ad.get('offer_id')} passed review."
    ad_vector, memory_vector = embeddings.embed_documents([campaigns.search_document(ex.description, ex.summary), episodic])
    new = campaigns.submit(
        identity, run_id, name=ad.get("name"), text=outcome.copy, ctx=ctx, facts=ex.facts().model_dump(), summary=ex.summary,
        description=ex.description, modality=modality, file_id=file_id, mime=mime, compliance=passing, cache_key=outcome.review.cache_key,
        campaign_id=campaign_id, source="regenerated", derived_from=ad.get("version", 1), vector=ad_vector, db=db,
    )
    memory.remember(identity, run_id, kind="episodic", text=episodic, scope={"team": identity.team, "user_id": None}, ttl_days=EPISODIC_TTL_DAYS, source_type="agent", vector=memory_vector, db=db)
    return {
        "status": "regenerated", "campaign": campaigns.card(new), "report": passing.model_dump(), "attempts": outcome.attempts,
        "reply": f"Version {new.get('version')} passes the same review as any other ad. It is pending review and still needs a manager's approval.",
    }


# ---------------------------------------------------------------- questions about an ad


class Answer(BaseModel):
    answer: str = Field(description="The reply to the colleague.")
    ad: Literal["A", "B", "none"] = Field(description="Which candidate ad the question is about. 'none' if neither fits.")
    basis: Literal["facts_and_offer", "needs_full_text", "not_covered"] = Field(
        description="'facts_and_offer' if the stored facts and the offer record answer it; 'needs_full_text' if the ad's full wording is needed; 'not_covered' if the ad and offer do not say."
    )


def _ad_block(label: str, ad: dict, offer: Optional[dict], with_text: bool) -> str:
    facts = ad.get("facts") or {}
    claims = "; ".join(f"[{c['type']}] {c['quote']}" for c in facts.get("claims", [])) or "none"
    lines = [f"<ad label=\"{label}\" name=\"{ad.get('name')}\" form=\"{ad.get('modality', 'text')}\" channel=\"{ad.get('channel')}\" language=\"{ad.get('language')}\" status=\"{ad.get('status')}\">", f"Summary: {ad.get('summary')}", f"Claims: {claims}", f"Call to action: {facts.get('cta') or 'none'}"]
    if with_text:
        lines.append(f"Full text: {ad.get('text')}")
    lines.append("</ad>")
    if offer:
        lines.append(compliance._offer_block(offer))
    return "\n".join(lines)


def ask_lane(identity: Identity, run_id: str, *, question: str, thread_campaign_id: Optional[str] = None, usage: Optional[llm.TokenUsage] = None, thread_id: Optional[str] = None, db=None) -> dict:
    db = db if db is not None else get_db()
    usage = usage or llm.TokenUsage()

    def answer() -> dict:
        # Candidates: the ad this conversation is already about, and the closest ad the caller may see.
        candidates: list[dict] = []
        if thread_campaign_id:
            try:
                candidates.append(campaigns.get(identity, thread_campaign_id, db))
            except campaigns.NotFound:
                pass
        for hit in campaigns.search_by_vector(identity, embeddings.embed_queries([question])[0], 1, db):
            if all(str(hit["_id"]) != str(c["_id"]) for c in candidates):
                candidates.append(hit)
        if not candidates:
            scope = "released ad" if identity.role == "sales" else "ad"
            return {"reply": f"I could not find a {scope} that matches. Try describing what the customer saw or heard.", "ad": None, "grounding": Grounding(band="low", note="No matching ad in your scope")}

        labels = ["A", "B"]
        offer_cache = {c.get("offer_id"): offers.get(c.get("offer_id"), db) for c in candidates}
        in_thread = thread_campaign_id and str(candidates[0]["_id"]) == str(thread_campaign_id)

        def ask(with_text: bool) -> Answer:
            blocks = "\n\n".join(_ad_block(labels[i], c, offer_cache.get(c.get("offer_id")), with_text) for i, c in enumerate(candidates))
            if in_thread:
                blocks += "\n\n<conversation>Ad A is the ad this conversation is about.</conversation>"
            return llm.call_structured(llm.fast_model(), Answer, system=prompts.answer_system(), user=f"{blocks}\n\n<question>\n{question}\n</question>", label="answer_full_text" if with_text else "answer", usage=usage, run_id=run_id, intent="ask")

        result = ask(False)
        band = "high"
        if result.basis == "needs_full_text":
            result, band = ask(True), "medium"
        if result.basis == "not_covered" or result.ad == "none":
            band = "low"
        chosen = candidates[labels.index(result.ad)] if result.ad in labels[: len(candidates)] else candidates[0]
        offer = offer_cache.get(chosen.get("offer_id"))
        sources = [{"type": "ad", "id": str(chosen["_id"]), "version": chosen.get("version", 1), "fields": ["facts", "summary"] + (["text"] if band == "medium" else [])}]
        if offer:
            sources.append({"type": "offer", "id": offer["_id"], "version": offer.get("version", 1), "fields": ["intro_rate", "standard_rate_percent", "bonus", "annual_fee", "eligibility"]})
        note = "The ad and the offer record do not cover this" if band == "low" else None
        return {"reply": result.answer, "ad": chosen, "grounding": Grounding(band=band, sources=sources, note=note)}

    out = gate.guarded(
        identity, "campaign.ask", {"question": question}, run_id, answer, thread_id=thread_id, db=db, tokens=usage.as_dict,
        summarize=lambda o: {"status": "ok", "summary": f"Answered about '{o['ad'].get('name')}'" if o["ad"] else "No matching ad in scope", "ref": {"collection": "campaigns", "id": str(o["ad"]["_id"])} if o["ad"] else None},
    )
    cards = [{"type": "campaign", "data": campaigns.card(out["ad"])}] if out["ad"] else []
    return {"reply": out["reply"], "cards": cards, "memories_used": [], "status": "completed", "grounding": out["grounding"].model_dump(), "campaign_id": str(out["ad"]["_id"]) if out["ad"] else None}


# ---------------------------------------------------------------- memory updates (draft only)


class DraftChange(BaseModel):
    kind: Literal["new_instruction", "edit_policy", "correct_memory", "forget_memory", "needs_clarification"]
    text: Optional[str] = Field(None, description="The full text to store: the instruction, the new clause text, or the corrected memory.")
    memory_kind: Optional[Literal["procedural", "semantic"]] = Field(None, description="For a new instruction: 'procedural' for a rule about how ads must be written, 'semantic' for a fact about the team.")
    policy_key: Optional[str] = Field(None, description="For edit_policy: the key of the clause, exactly as listed.")
    memory_id: Optional[str] = Field(None, description="For correct_memory or forget_memory: the id, exactly as listed.")
    question: Optional[str] = Field(None, description="For needs_clarification: what you need to know.")


def memory_update_lane(identity: Identity, run_id: str, *, message: str, usage: Optional[llm.TokenUsage] = None, thread_id: Optional[str] = None, db=None) -> dict:
    """Draft a change to what the agent knows. Nothing is written here.

    The web app shows the proposal, collects the password and reason, and calls the write endpoint.
    The password never passes through this function or the model.
    """
    db = db if db is not None else get_db()
    usage = usage or llm.TokenUsage()
    manager = identity.role == "manager"

    def draft() -> dict:
        mine = memory.list_scoped(identity, status="active", db=db)
        if not manager:
            mine = [m for m in mine if m["scope"].get("user_id") == identity.user_id]
        memory_lines = [f"- id {m['id']} ({m['kind']}): {m['text']}" for m in mine[:30]] or ["- none"]
        parts = [f"<manager_team>{identity.team}</manager_team>" if manager else "<note>This person is not a manager. They may only add, correct or forget a personal note of their own; they cannot edit a policy or a team instruction.</note>"]
        if manager:
            clauses = fundamentals.list_all(identity, db)
            parts.append("<policy_clauses>\n" + "\n".join(f"- {c['key']} (version {c.get('version', 1)}): {c['title']}. {c.get('summary', '')}" for c in clauses if c.get("status") == "approved") + "\n</policy_clauses>")
        parts.append("<memories>\n" + "\n".join(memory_lines) + "\n</memories>")
        parts.append(f"<message>\n{message}\n</message>")
        d: DraftChange = llm.call_structured(llm.fast_model(), DraftChange, system=prompts.draft_change_system(), user="\n\n".join(parts), label="draft_change", usage=usage, run_id=run_id, intent="memory_update")
        return _proposal(d, identity, mine, db)

    proposal = gate.guarded(
        identity, "memory.write", {"step": "draft", "message": message}, run_id, draft, thread_id=thread_id, db=db, tokens=usage.as_dict,
        summarize=lambda p: {"status": "ok", "summary": "Drafted a proposed change; nothing saved until it is confirmed" if p["card"] else "Asked for clarification"},
    )
    return {"reply": proposal["reply"], "cards": [proposal["card"]] if proposal["card"] else [], "memories_used": [], "status": "completed"}


def _proposal(d: DraftChange, identity: Identity, mine: list[dict], db) -> dict:
    manager = identity.role == "manager"
    by_id = {m["id"]: m for m in mine}
    if d.kind == "edit_policy" and manager and d.policy_key:
        try:
            clause = fundamentals.get(d.policy_key, db)
        except fundamentals.NotFound:
            clause = None
        if clause and d.text:
            card = {"target": "fundamental", "id": str(clause["_id"]), "key": clause["key"], "before": clause["text"], "after": d.text, "version": clause.get("version", 1), "status": "proposed", "requires_password": True}
            return {"card": {"type": "memory_change", "data": card}, "reply": f"Proposed change to {clause['key']} (currently version {clause.get('version', 1)}). Confirm it with your password and a reason to save it."}
    if d.kind in ("correct_memory", "forget_memory") and d.memory_id in by_id:
        m = by_id[d.memory_id]
        team_scope = m["scope"].get("user_id") is None
        card = {"target": "memory", "id": m["id"], "kind": m["kind"], "scope": m["scope"], "before": m["text"], "after": None if d.kind == "forget_memory" else d.text, "action": "forget" if d.kind == "forget_memory" else "correct", "status": "proposed", "requires_password": team_scope}
        verb = "forget" if d.kind == "forget_memory" else "correct"
        return {"card": {"type": "memory_change", "data": card}, "reply": f"Proposed: {verb} this memory." + (" Confirm it with your password and a reason." if team_scope else " Confirm to save.")}
    if d.kind == "new_instruction" and d.text:
        scope = {"team": identity.team, "user_id": None if manager else identity.user_id}
        kind = (d.memory_kind or "procedural") if manager else "semantic"
        card = {"target": "memory", "id": None, "kind": kind, "scope": scope, "before": None, "after": d.text, "action": "create", "status": "proposed", "requires_password": manager}
        who = f"the {identity.team} team" if manager else "you only"
        return {"card": {"type": "memory_change", "data": card}, "reply": f"Proposed new {'instruction' if kind == 'procedural' else 'note'} for {who}." + (" Confirm it with your password and a reason to save it." if manager else " Confirm to save.")}
    return {"card": None, "reply": d.question or "I could not tell which policy or memory you mean. Name the policy, or quote the instruction you want changed."}
