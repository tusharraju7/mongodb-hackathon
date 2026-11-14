"""Checks that need no model: budget cap, banned terms, required lines, ad numbers against the offer.

Pure functions over plain dicts. Nothing here touches the database or a model, so every rule can be
unit-tested against the seed files.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"', " ": " ", " ": " "})


def norm(text: str) -> str:
    """Lowercase, straighten quotes and collapse whitespace, so matching ignores typography."""
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES).lower()).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True when the quoted words appear in the ad. Edge punctuation is ignored."""
    q = norm(quote).strip(" .,;:!?\"'")
    return bool(q) and q in norm(text)


def _money(amount: Any) -> str:
    try:
        return f"{float(amount):,.0f}" if float(amount) == int(float(amount)) else f"{float(amount):,.2f}"
    except (TypeError, ValueError):
        return str(amount)


def _finding(clause: dict, *, source: str, quote: str, explanation: str, reasoning: str, fix: str, evidence: dict) -> dict:
    return {
        "source": source,
        "basis": "code",
        "fundamental_key": clause["key"],
        "version": clause.get("version", 1),
        "materiality": clause.get("materiality", "material"),
        "quote": quote,
        "explanation": explanation,
        "reasoning": reasoning,
        "evidence": evidence,
        "fix": fix,
    }


def required_line_for(clause: dict, language: str) -> Optional[str]:
    lines = (clause.get("rule") or {}).get("lines") or {}
    return lines.get(language) or lines.get("en")


def approved_fix_for(clause: dict, language: str) -> Optional[str]:
    fix = clause.get("approved_fix") or {}
    return fix.get(language) or fix.get("en")


def check_budget(clause: dict, ctx: dict) -> tuple[list[dict], list[dict]]:
    rule = clause["rule"]
    if rule.get("team") != ctx.get("team"):
        return [], []
    budget = ctx.get("budget") or {}
    amount = budget.get("amount")
    if amount is None:
        return [], [{"check": "budget_cap", "detail": "No budget given, so the cap was not checked"}]
    cap = rule["max"]
    currency = rule.get("currency", "CAD")
    if amount > cap:
        return [
            _finding(
                clause,
                source="fundamental",
                quote="",
                explanation=f"The budget of {currency} {_money(amount)} is over the {ctx['team']} team cap of {currency} {_money(cap)}.",
                reasoning=f"The campaign budget is {currency} {_money(amount)}. The cap for the {ctx['team']} team is {currency} {_money(cap)} without written approval.",
                fix=f"Reduce the budget to {currency} {_money(cap)} or less, or attach written approval.",
                evidence={"policy_excerpt": clause.get("text"), "ad_value": amount, "offer_value": cap},
            )
        ], []
    return [], [{"check": "budget_cap", "detail": f"{currency} {_money(amount)} is within the {ctx['team']} team cap of {currency} {_money(cap)}"}]


def check_banned_terms(clause: dict, text: str) -> tuple[list[dict], list[dict]]:
    found = []
    for term in clause["rule"].get("terms", []):
        m = re.search(re.escape(norm(term)), norm(text))
        if m:
            found.append(term)
    if not found:
        return [], [{"check": "banned_terms", "detail": "No competitor names"}]
    return [
        _finding(
            clause,
            source="fundamental",
            quote=term,
            explanation=f"The ad names a competitor: {term}.",
            reasoning=f"The ad mentions {term}. Policy does not allow naming another financial institution or its products.",
            fix=f"Remove the reference to {term}.",
            evidence={"policy_excerpt": clause.get("text")},
        )
        for term in found
    ], []


def check_required_line(clause: dict, text: str, ctx: dict) -> tuple[list[dict], list[dict]]:
    rule = clause["rule"]
    if rule.get("channel") and rule["channel"] != ctx.get("channel"):
        return [], []
    language = ctx.get("language") or "en"
    line = required_line_for(clause, language)
    if not line:
        return [], []
    if norm(line).strip(" .") in norm(text):
        return [], [{"check": f"required_line.{clause['key']}", "detail": f"Contains: {line}"}]
    fix_text = approved_fix_for(clause, language) or line
    return [
        _finding(
            clause,
            source="fundamental",
            quote="",
            explanation=f"A required line is missing: {line}",
            reasoning=f"This kind of ad must carry the line \"{line}\". It does not appear in the ad.",
            fix=f"Add: {fix_text}",
            evidence={"policy_excerpt": clause.get("text")},
        )
    ], []


def check_offer_match(clause: dict, claims: list[dict], offer: dict) -> tuple[list[dict], list[dict]]:
    """Compare every number the ad states with the approved offer record."""
    findings: list[dict] = []
    passed: list[dict] = []
    offer_id = offer.get("_id")

    def mismatch(claim: dict, field: str, ad_value: Any, offer_value: Any, what: str, fix: str) -> None:
        findings.append(
            _finding(
                clause,
                source="offer",
                quote=claim.get("quote", ""),
                explanation=f"The ad states {what} of {ad_value}; the approved offer {offer_id} says {offer_value}.",
                reasoning=f"The ad says {what} is {ad_value}. The approved offer {offer_id} sets it at {offer_value}, so the ad misstates the offer.",
                fix=fix,
                evidence={"offer_field": field, "ad_value": ad_value, "offer_value": offer_value},
            )
        )

    for claim in claims:
        values = claim.get("values") or {}
        ctype = claim.get("type")
        if ctype == "intro_rate":
            intro = offer.get("intro_rate")
            if intro is None:
                if values:
                    mismatch(claim, "intro_rate", claim.get("quote"), "no introductory rate", "an introductory rate", "Remove the introductory rate claim; this offer has none.")
                continue
            if values.get("months") is not None:
                if int(values["months"]) != int(intro["months"]):
                    mismatch(claim, "intro_rate.months", int(values["months"]), int(intro["months"]), "an introductory period, in months,", f"Change {int(values['months'])} months to {int(intro['months'])} months.")
                else:
                    passed.append({"check": "offer_match.intro_months", "detail": f"{int(intro['months'])} months matches the offer"})
            if values.get("rate_percent") is not None:
                if float(values["rate_percent"]) != float(intro["rate_percent"]):
                    mismatch(claim, "intro_rate.rate_percent", values["rate_percent"], intro["rate_percent"], "an introductory rate, in percent,", f"Change the introductory rate to {intro['rate_percent']}%.")
                else:
                    passed.append({"check": "offer_match.intro_rate", "detail": f"{_money(intro['rate_percent'])}% matches the offer"})
        elif ctype == "rewards_bonus" and values.get("amount") is not None:
            bonus = offer.get("bonus")
            if bonus is None:
                mismatch(claim, "bonus", values["amount"], "no bonus", "a bonus amount", "Remove the bonus claim; this offer has none.")
            elif float(values["amount"]) != float(bonus["amount"]):
                mismatch(claim, "bonus.amount", values["amount"], bonus["amount"], "a bonus amount, in dollars,", f"Change the bonus to ${_money(bonus['amount'])}.")
            else:
                passed.append({"check": "offer_match.bonus_amount", "detail": f"${_money(bonus['amount'])} matches the offer"})
        elif ctype == "annual_fee" and values.get("fee") is not None:
            fee = offer.get("annual_fee")
            if fee is not None and float(values["fee"]) != float(fee):
                said = "no annual fee" if float(values["fee"]) == 0 else f"an annual fee of ${_money(values['fee'])}"
                findings.append(
                    _finding(
                        clause,
                        source="offer",
                        quote=claim.get("quote", ""),
                        explanation=f"The ad states {said}; the approved offer {offer_id} has an annual fee of ${_money(fee)}.",
                        reasoning=f"The ad says the card has {said}. The approved offer {offer_id} sets the annual fee at ${_money(fee)}, so the ad misstates the offer.",
                        fix=f"State the annual fee as ${_money(fee)}.",
                        evidence={"offer_field": "annual_fee", "ad_value": values["fee"], "offer_value": fee},
                    )
                )
            elif fee is not None:
                passed.append({"check": "offer_match.annual_fee", "detail": f"${_money(fee)} matches the offer"})
    return findings, passed


def run_hard_rules(text: str, ctx: dict, claims: list[dict], offer: dict, clauses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run every clause that carries a `rule`. Returns (findings, passed_checks)."""
    findings: list[dict] = []
    passed: list[dict] = []
    for clause in clauses:
        rule = clause.get("rule") or {}
        kind = rule.get("type")
        if kind == "budget_cap":
            f, p = check_budget(clause, ctx)
        elif kind == "banned_terms":
            f, p = check_banned_terms(clause, text)
        elif kind == "required_line":
            f, p = check_required_line(clause, text, ctx)
        elif kind == "offer_match":
            f, p = check_offer_match(clause, claims, offer)
        else:
            continue
        findings += f
        passed += p
    return findings, passed


def ensure_required_lines(copy: str, ctx: dict, clauses: list[dict]) -> str:
    """Append any required line the corrected copy still lacks, using the approved wording."""
    language = ctx.get("language") or "en"
    out = (copy or "").strip()
    for clause in clauses:
        rule = clause.get("rule") or {}
        if rule.get("type") != "required_line":
            continue
        if rule.get("channel") and rule["channel"] != ctx.get("channel"):
            continue
        line = required_line_for(clause, language)
        if line and norm(line).strip(" .") not in norm(out):
            out = f"{out} {approved_fix_for(clause, language) or line}".strip()
    return out


# Clauses fully decided in code. The judge is not shown these, so it cannot duplicate or contradict them.
CODE_ONLY_RULES = {"budget_cap", "required_line", "offer_match"}


def decided_in_code(clause: dict) -> bool:
    return (clause.get("rule") or {}).get("type") in CODE_ONLY_RULES
