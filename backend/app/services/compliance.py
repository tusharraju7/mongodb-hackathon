"""UC1: review an ad, and regenerate a compliant version.

`review()` runs the fixed order from docs/FLOWS.md. Everything it reads comes through a `Sources`
object, so the same code runs against MongoDB in the app and against the seed files in the dry run.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

from app.agent import prompts
from app.core import embeddings, llm
from app.core.profile import get_profile
from app.models import (
    ComplianceReport,
    Extraction,
    Identity,
    JudgeOutput,
    RepairOutput,
    regions_for,
)
from app.services import compliance_rules as rules
from app.services import confidence as conf

MAX_JUDGE_CLAUSES = 16
SIMILAR_PER_QUERY = 2
FULL_TEXT_LIMIT = 1200  # clauses longer than this are shown to the judge as their summary

# How a memory stands relative to policy. Stored on the memory as `authority`; derived from its kind when absent.
STANDING = {
    "binding": "binding internal decision",
    "guidance": "team guidance",
    "precedent": "past verdict",
    "background": "background, may be out of date",
}


def authority_of(memory: dict) -> str:
    return memory.get("authority") or {"episodic": "precedent", "procedural": "binding"}.get(memory.get("kind"), "background")


class Sources(Protocol):
    """Everything a review reads. Implemented over MongoDB and over the seed files."""

    def offer(self, offer_id: str) -> Optional[dict]: ...
    def applicable_clauses(self, regions: list[str], product: str) -> list[dict]: ...
    def similar_clauses(self, vectors: list[list[float]], regions: list[str], product: str, k: int) -> list[list[tuple[dict, float]]]: ...
    def recall(self, identity: Identity, vectors: list[list[float]], kinds: list[str], per_query: int, budget: int) -> list[dict]: ...


@dataclass
class ReviewResult:
    report: ComplianceReport
    extraction: Optional[Extraction] = None
    offer: Optional[dict] = None
    cache_key: Optional[str] = None
    code_clauses: list[dict] = field(default_factory=list)


def default_sources() -> Sources:
    from app.services.mongo_sources import MongoSources

    return MongoSources()


# ---------------------------------------------------------------- claim extraction


def extract_claims(text: str, ctx: dict, *, usage: Optional[llm.TokenUsage] = None, run_id: Optional[str] = None) -> Extraction:
    """One fast-model call. Its output also becomes the ad's stored facts, so it is paid for once."""
    form = {"audio": "a transcript of a spoken ad", "image": "text read from an image ad"}.get(ctx.get("modality"), "ad copy")
    user = f"Channel: {ctx.get('channel', 'unknown')}. Form: {form}.\n\n<ad>\n{text}\n</ad>"
    extraction = llm.call_structured(
        llm.fast_model(), Extraction, system=prompts.extract_system(), user=user, label="extract_claims", usage=usage, run_id=run_id, intent="review"
    )
    # A claim whose quote is not in the ad cannot be trusted; drop it before anything is checked against it.
    extraction.claims = [c for c in extraction.claims if rules.quote_in_text(c.quote, text)]
    return extraction


# ---------------------------------------------------------------- prompt assembly


def _offer_block(offer: dict) -> str:
    lines = [f"<offer id=\"{offer['_id']}\" version=\"{offer.get('version', 1)}\">", f"Card: {offer.get('card_name')} (French: {offer.get('card_name_fr', 'n/a')})"]
    intro = offer.get("intro_rate")
    if intro:
        lines.append(f"Introductory rate: {intro['rate_percent']}% on {intro.get('applies_to', 'purchases')} for {intro['months']} months")
    else:
        lines.append("Introductory rate: none")
    lines.append(f"Standard annual interest rate after any introductory period: {offer.get('standard_rate_percent')}%")
    bonus = offer.get("bonus")
    if bonus:
        months = round(bonus["window_days"] / 30)
        lines.append(
            f"Bonus: ${bonus['amount']:,} cash back after ${bonus['qualifying_spend']:,} in purchases within "
            f"{bonus['window_days']} days (the first {months} months)"
        )
    else:
        lines.append("Bonus: none")
    lines.append(f"Annual fee: ${offer.get('annual_fee'):,}")
    lines.append(f"Eligibility: {offer.get('eligibility', 'n/a')}")
    lines.append("</offer>")
    return "\n".join(lines)


def _clause_block(clause: dict, languages: list[str], mandatory_types: list[str]) -> str:
    body = clause["text"] if len(clause.get("text", "")) <= FULL_TEXT_LIMIT else clause.get("summary", "")
    head = f"- {clause['key']} (version {clause.get('version', 1)}, {clause.get('materiality')})"
    if mandatory_types:
        head += f" [applies to the ad's {', '.join(mandatory_types)} claim]"
    out = f"{head}: {body}"
    wording = clause.get("approved_fix") or {}
    for language in languages:
        if wording.get(language):
            out += f"\n  Approved wording ({language}): {wording[language]}"
    return out


def _required_lines_block(code_clauses: list[dict], ctx: dict, languages: list[str]) -> str:
    """The lines the corrected copy must carry, so the judge writes them in the right language."""
    lines = []
    for clause in code_clauses:
        rule = clause.get("rule") or {}
        if rule.get("type") not in ("required_line", "required_elements") or (rule.get("channel") and rule["channel"] != ctx.get("channel")):
            continue
        wording = clause.get("approved_fix") or rule.get("lines") or {}
        lines.append("- " + " / ".join(f"({lang}) {wording[lang]}" for lang in languages if wording.get(lang)))
    return "<required_lines>\n" + ("\n".join(lines) or "- none") + "\n</required_lines>"


def _judge_user(
    text: str, ctx: dict, extraction: Extraction, offer: Optional[dict], code_findings: list[dict], code_clauses: list[dict],
    clauses: list[tuple[dict, list[str]]], memories: list[dict],
) -> str:
    language = ctx.get("language") or extraction.language
    # A Quebec ad may need to be rewritten in French, so the judge sees French wording as well.
    languages = list(dict.fromkeys([language] + (["fr"] if ctx.get("region") == "CA-QC" else [])))
    form = {"audio": "transcript of a spoken ad", "image": "text read from an image"}.get(ctx.get("modality"), "typed text")
    parts = [
        f"<ad region=\"{ctx.get('region')}\" channel=\"{ctx.get('channel')}\" language=\"{language}\" form=\"{form}\">\n{text}\n</ad>",
    ]
    if ctx.get("visual_notes"):
        parts.append(f"<image_notes>\n{ctx['visual_notes']}\n</image_notes>")
    claim_lines = [f"- [{c.type}] \"{c.quote}\"" for c in extraction.claims] or ["- none"]
    parts.append("<claims>\n" + "\n".join(claim_lines) + "\n</claims>")
    if offer:
        parts.append(_offer_block(offer))
    found = [f"- {f['fundamental_key']}: {f['explanation']} Fix: {f['fix']}" for f in code_findings] or ["- none"]
    parts.append("<already_found_by_automated_checks>\n" + "\n".join(found) + "\n</already_found_by_automated_checks>")
    parts.append(_required_lines_block(code_clauses, ctx, languages))
    parts.append("<policy_clauses>\n" + "\n".join(_clause_block(c, languages, m) for c, m in clauses) + "\n</policy_clauses>")
    mem = []
    for m in memories:
        where = ", ".join(x for x in (m.get("source_label"), m.get("date")) if x)
        mem.append(f"- id {m['id']} [{STANDING[authority_of(m)]}{'; ' + where if where else ''}]: {m['text']}")
    mem = mem or ["- none"]
    parts.append("<team_memories>\n" + "\n".join(mem) + "\n</team_memories>")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- the review


def _missing_offer_report(offer_id: Optional[str]) -> ComplianceReport:
    what = f"offer record {offer_id}" if offer_id else "offer_id"
    verdict, route, reason = conf.base_verdict([], [what])
    return ComplianceReport(
        verdict=verdict,
        route=route,
        route_reason=reason,
        summary="This ad could not be reviewed because no approved offer record was found for it. Choose the offer it promotes and submit it again.",
        confidence=conf.verdict_confidence(verdict, [], [what], quality=1.0, quality_reason="", claims=[], coverage=0, uncovered=0),
        missing_inputs=["offer_id"],
    )


def _cache_key(text: str, offer: Optional[dict], clauses: list[dict], memories: list[dict], ctx: dict) -> str:
    payload = {
        "text": rules.norm(text),
        "offer": [offer["_id"], offer.get("version", 1)] if offer else None,
        "clauses": sorted([c["key"], c.get("version", 1)] for c in clauses),
        "memories": sorted(m["id"] for m in memories),
        "ctx": [ctx.get("region"), ctx.get("channel"), ctx.get("language"), ctx.get("team"), (ctx.get("budget") or {}).get("amount"), ctx.get("visual_notes")],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def review(
    text: str,
    ctx: dict,
    identity: Identity,
    run_id: str,
    *,
    use_memory: bool = True,
    sources: Optional[Sources] = None,
    usage: Optional[llm.TokenUsage] = None,
    extraction: Optional[Extraction] = None,
    cached_report: Optional[callable] = None,
) -> ReviewResult:
    """Review one ad. `ctx` is the AdContext as a dict, plus `team` taken from the identity."""
    sources = sources or default_sources()
    ctx = {**ctx, "team": ctx.get("team") or identity.team}

    profile = get_profile()

    # 1. Where an ad names an offer, that record is the system of record: if it cannot be found,
    #    nothing is checked and nothing is invented. An ad that names none is reviewed without one.
    offer = None
    if ctx.get("offer_id"):
        offer = sources.offer(ctx["offer_id"])
        if offer is None:
            return ReviewResult(report=_missing_offer_report(ctx["offer_id"]))

    # 2. Claims, once.
    extraction = extraction or extract_claims(text, ctx, usage=usage, run_id=run_id)
    ctx["language"] = ctx.get("language") or extraction.language
    claims = [c.model_dump() for c in extraction.facts().claims]

    # 3. Checks in code.
    ctx["region"] = ctx.get("region") or profile["region"]
    ctx["product"] = ctx.get("product") or profile["product"]
    regions = regions_for(ctx["region"])
    product = ctx["product"]
    applicable = sources.applicable_clauses(regions, product)
    code_clauses = [c for c in applicable if c.get("rule")]
    code_findings, passed = rules.run_hard_rules(text, ctx, claims, offer, code_clauses)

    # 4. Which clauses the judge sees: mandatory for a claim type first, then general clauses that no
    #    claim would lead to, then the closest matches by meaning. Clauses decided in code are left out.
    judgeable = [c for c in applicable if not rules.decided_in_code(c)]
    claim_types = [c["type"] for c in claims]
    # One embedding request covers the whole ad and each claim; the ad's vector is reused for memory.
    queries = [text] + [c["quote"] for c in claims]
    vectors = embeddings.embed_queries(queries)
    ranked = sources.similar_clauses(vectors, regions, product, SIMILAR_PER_QUERY + 1)
    similarity: dict[str, float] = {}
    best_for_claim: dict[int, float] = {}
    for qi, hits in enumerate(ranked):
        for clause, score in hits:
            similarity[clause["key"]] = max(similarity.get(clause["key"], 0.0), score)
            if qi > 0:
                best_for_claim[qi - 1] = max(best_for_claim.get(qi - 1, 0.0), score)

    def mandatory_types(clause: dict) -> list[str]:
        return [t for t in dict.fromkeys(claim_types) if t in (clause.get("claim_types") or [])]

    def rank(clause: dict) -> tuple:
        general = not clause.get("claim_types")
        return (0 if mandatory_types(clause) else 1 if general else 2, -similarity.get(clause["key"], 0.0))

    shown = sorted(judgeable, key=rank)
    if len(shown) > MAX_JUDGE_CLAUSES:
        # Too many to show them all: keep the mandatory and general ones, and the closest of the rest.
        shown = [c for c in shown[:MAX_JUDGE_CLAUSES] if mandatory_types(c) or not c.get("claim_types") or c["key"] in similarity]
    consulted = shown + code_clauses

    # 5. Memory: binding decisions, guidance, past verdicts and background, scoped by the source and
    #    searched once for the whole ad and once for each claim, so a single named person or phrase
    #    can find the decision about it.
    memories = (
        sources.recall(identity, vectors, ["procedural", "episodic", "semantic"], profile["memory"]["per_query"], profile["memory"]["budget"])
        if use_memory else []
    )

    # 6. A stored verdict for exactly this text, offer, clause versions and memories skips the judge.
    key = _cache_key(text, offer, consulted, memories, ctx)
    if cached_report is not None:
        hit = cached_report(key)
        if hit is not None:
            hit.cached = True
            return ReviewResult(report=hit, extraction=extraction, offer=offer, cache_key=key, code_clauses=code_clauses)

    # 7. The verdict.
    judged: JudgeOutput = llm.call_structured(
        llm.main_model(),
        JudgeOutput,
        system=prompts.judge_system(),
        user=_judge_user(text, ctx, extraction, offer, code_findings, code_clauses, [(c, mandatory_types(c)) for c in shown], memories),
        label="judge",
        usage=usage,
        run_id=run_id,
        intent="review",
    )

    # 8. Turn the judge's findings into violations. Anything citing an unknown clause or memory, or
    #    quoting words that are not in the ad, is dropped.
    by_key = {c["key"]: c for c in shown}
    by_memory = {m["id"]: m for m in memories}
    episodic_ids = {m["id"] for m in memories if m["kind"] == "episodic"}
    quality, quality_reason = conf.input_quality(ctx.get("modality", "text"), ctx.get("fine_print_legible"))
    dropped = 0
    violations: list[dict] = []

    for f in code_findings:
        f["confidence"] = conf.score_finding(f, quality=quality, quality_reason=quality_reason, quote_verified=bool(f["quote"]))
        violations.append(f)

    for jf in judged.findings:
        quote_ok = rules.quote_in_text(jf.quote, text) if jf.quote.strip() else False
        if jf.quote.strip() and not quote_ok:
            dropped += 1
            continue
        agrees = jf.agrees_with_memory in episodic_ids if jf.agrees_with_memory else False
        if jf.source == "policy" and jf.ref in by_key:
            clause = by_key[jf.ref]
            v = {
                "source": "fundamental", "basis": "model", "certainty": jf.certainty,
                "fundamental_key": clause["key"], "version": clause.get("version", 1),
                "materiality": clause.get("materiality", "material"),
                "quote": jf.quote.strip(), "explanation": jf.explanation, "reasoning": jf.reasoning,
                "evidence": {"policy_excerpt": clause["text"][:400]}, "fix": jf.fix,
            }
            v["confidence"] = conf.score_finding(
                v, quality=quality, quality_reason=quality_reason, quote_verified=quote_ok,
                mandatory_types=mandatory_types(clause), applies_to_all=not clause.get("claim_types"),
                from_similarity=clause["key"] in similarity, past_verdict_agrees=agrees,
            )
        elif jf.source == "memory" and jf.ref in by_memory:
            memory = by_memory[jf.ref]
            v = {
                "source": "memory", "basis": "model", "certainty": jf.certainty, "memory_id": memory["id"],
                # A binding decision can carry its own weight; a plain team instruction asks for changes.
                "materiality": memory.get("materiality") or "disclosure", "quote": jf.quote.strip(), "explanation": jf.explanation,
                "reasoning": jf.reasoning, "evidence": {"memory_text": memory["text"][:600]}, "fix": jf.fix,
            }
            v["confidence"] = conf.score_finding(
                v, quality=quality, quality_reason=quality_reason, quote_verified=quote_ok,
                standing_instruction=authority_of(memory) in ("binding", "guidance"), past_verdict_agrees=agrees,
            )
        else:
            dropped += 1
            continue
        violations.append(v)

    if dropped:
        passed.append({"check": "dropped_findings", "detail": dropped})

    # 9. Verdict, confidence and route, all in code.
    verdict, route, reason = conf.base_verdict(violations, [])
    coverage, uncovered = conf.claim_coverage(claims, consulted, best_for_claim)
    confidence = conf.verdict_confidence(
        verdict, violations, [], quality=quality, quality_reason=quality_reason, claims=claims, coverage=coverage, uncovered=uncovered,
        complete=len(shown) == len(judgeable),
    )
    route, reason = conf.escalate(verdict, route, reason, confidence, violations)

    corrected = corrected_language = None
    if verdict != "pass":
        corrected_language = judged.corrected_copy_language
        corrected = rules.ensure_required_lines(judged.corrected_copy, {**ctx, "language": corrected_language}, code_clauses)

    report = ComplianceReport(
        verdict=verdict,
        decision=profile["decision_labels"].get(verdict),
        route=route,
        route_reason=reason,
        summary=judged.summary or _DEFAULT_PASS_SUMMARY,
        confidence=confidence,
        passed_checks=passed,
        violations=violations,
        corrected_copy=corrected,
        corrected_language=corrected_language,
        checked_fundamentals=[{"key": c["key"], "version": c.get("version", 1)} for c in consulted],
        offer_version=offer.get("version", 1) if offer else None,
        # Every recalled memory was in front of the judge, so every one may have shaped the result.
        # The ones a finding rests on are also named on that finding as `memory_id`.
        memories_used=[m["id"] for m in memories],
    )
    return ReviewResult(report=report, extraction=extraction, offer=offer, cache_key=key, code_clauses=code_clauses)


_DEFAULT_PASS_SUMMARY = "No problems were found. The ad meets the policies and internal decisions that apply to it."


def check(text: str, ctx: dict, identity: Identity, run_id: str, *, use_memory: bool = True, sources: Optional[Sources] = None, usage: Optional[llm.TokenUsage] = None) -> ComplianceReport:
    """The contract's entry point: a report only."""
    return review(text, ctx, identity, run_id, use_memory=use_memory, sources=sources, usage=usage).report


# ---------------------------------------------------------------- regeneration (copy only)


@dataclass
class RegeneratedCopy:
    status: str  # "regenerated" | "failed"
    copy: Optional[str]
    review: ReviewResult
    attempts: int


def regenerate_copy(
    text: str,
    report: ComplianceReport,
    ctx: dict,
    identity: Identity,
    run_id: str,
    *,
    sources: Optional[Sources] = None,
    usage: Optional[llm.TokenUsage] = None,
) -> RegeneratedCopy:
    """Produce copy that passes the same review as any ad, or nothing.

    The corrected copy already in the report is reviewed first, so the usual case costs no new
    writing. If it does not pass there is one repair attempt. Rendering to audio or an image happens
    in the caller, and only after this returns "regenerated".
    """
    sources = sources or default_sources()
    if report.missing_inputs or not report.corrected_copy:
        return RegeneratedCopy("failed", None, ReviewResult(report=report), 0)

    candidate = report.corrected_copy
    # The corrected copy is typed text whatever the original form was, and may be in another language.
    copy_ctx = {**ctx, "modality": "text", "visual_notes": None, "fine_print_legible": None}
    copy_ctx["language"] = report.corrected_language or ctx.get("language")
    first = review(candidate, copy_ctx, identity, run_id, sources=sources, usage=usage)
    if first.report.verdict == "pass":
        return RegeneratedCopy("regenerated", candidate, first, 1)

    problems = "\n".join(f"- {v.explanation} Fix: {v.fix}" for v in first.report.violations)
    offer_part = f"\n\n{_offer_block(first.offer)}" if first.offer else ""
    user = f"<ad language=\"{copy_ctx.get('language', 'en')}\" channel=\"{copy_ctx.get('channel')}\">\n{candidate}\n</ad>{offer_part}\n\n<problems>\n{problems}\n</problems>"
    repaired = llm.call_structured(llm.main_model(), RepairOutput, system=prompts.repair_system(), user=user, label="repair_copy", usage=usage, run_id=run_id, intent="regenerate")
    candidate = rules.ensure_required_lines(repaired.corrected_copy, copy_ctx, first.code_clauses)
    second = review(candidate, copy_ctx, identity, run_id, sources=sources, usage=usage)
    if second.report.verdict == "pass":
        return RegeneratedCopy("regenerated", candidate, second, 2)
    return RegeneratedCopy("failed", None, second, 2)


def now() -> datetime:
    return datetime.now(timezone.utc)
