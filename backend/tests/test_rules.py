"""The checks that need no model, proven against the seed files. No network, no database."""
from datetime import datetime, timezone

from app.models import regions_for
from app.services import compliance_rules as rules
from app.services.fixture_sources import clause_applies, load_seed

RUNNING = "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."
CLAIMS = [
    {"type": "approval", "quote": "Guaranteed approval!", "values": None},
    {"type": "intro_rate", "quote": "0% interest for 12 months", "values": {"rate_percent": 0, "months": 12}},
    {"type": "rewards_bonus", "quote": "earn $300 cash back", "values": {"amount": 300}},
]
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def clauses_for(region: str, product: str = "credit_card") -> list[dict]:
    return [c for c in load_seed("fundamentals") if clause_applies(c, regions_for(region), product, NOW)]


def offer(offer_id: str = "TCB-FALL-2026") -> dict:
    return next(o for o in load_seed("offers") if o["_id"] == offer_id)


def ctx(**over) -> dict:
    base = {"team": "national", "region": "CA", "channel": "email", "language": "en", "budget": {"amount": 20000, "currency": "CAD"}}
    return {**base, **over}


def run(text: str, claims: list[dict], context: dict, offer_id: str = "TCB-FALL-2026"):
    code_clauses = [c for c in clauses_for(context["region"]) if c.get("rule")]
    return rules.run_hard_rules(text, context, claims, offer(offer_id), code_clauses)


def keys(findings):
    return sorted(f["fundamental_key"] for f in findings)


def test_running_example_code_findings():
    findings, passed = run(RUNNING, CLAIMS, ctx())
    assert keys(findings) == ["brand.required_footer", "policy.offer_accuracy", "regional.ca.email_consent"]
    mismatch = next(f for f in findings if f["source"] == "offer")
    assert mismatch["evidence"] == {"offer_field": "intro_rate.months", "ad_value": 12, "offer_value": 10}
    assert mismatch["quote"] == "0% interest for 12 months"
    assert mismatch["materiality"] == "material"
    checks = {p["check"] for p in passed}
    assert {"budget_cap", "banned_terms", "offer_match.bonus_amount", "offer_match.intro_rate"} <= checks


def test_compliant_seeded_email_has_no_code_findings():
    ad = next(a for a in load_seed("campaigns") if a["ref"] == "nat-email-fall-cashback")
    findings, _ = run(ad["text"], ad["facts"]["claims"], ctx(budget=ad["budget"]))
    assert findings == []


def test_budget_over_cap_is_material():
    findings, _ = run(RUNNING, [], ctx(budget={"amount": 50000, "currency": "CAD"}))
    over = next(f for f in findings if f["fundamental_key"] == "budget.cap.national")
    assert over["materiality"] == "material" and over["evidence"]["offer_value"] == 25000


def test_quebec_team_uses_its_own_cap():
    findings, _ = run("x", [], ctx(team="quebec", region="CA-QC", language="fr", budget={"amount": 20000, "currency": "CAD"}))
    assert "budget.cap.quebec" in keys(findings) and "budget.cap.national" not in keys(findings)


def test_competitor_name_is_found_whatever_the_case():
    ad = next(a for a in load_seed("campaigns") if a["ref"] == "nat-social-rewards-switch")
    findings, _ = run(ad["text"].upper(), ad["facts"]["claims"], ctx(channel="social", budget=ad["budget"]), "TRC-WINTER-2026")
    assert "policy.competitor_mentions" in keys(findings)
    fee = next(f for f in findings if f["evidence"].get("offer_field") == "annual_fee")
    assert fee["evidence"]["ad_value"] == 0 and fee["evidence"]["offer_value"] == 99


def test_unsubscribe_line_only_required_for_email():
    radio, _ = run("Conditions apply.", [], ctx(channel="radio"))
    email, _ = run("Conditions apply.", [], ctx(channel="email"))
    assert "regional.ca.email_consent" not in keys(radio)
    assert "regional.ca.email_consent" in keys(email)


def test_french_ad_needs_the_french_lines():
    ad = next(a for a in load_seed("campaigns") if a["ref"] == "qc-email-remises")
    quebec = ctx(team="quebec", region="CA-QC", language="fr", budget=ad["budget"])
    assert run(ad["text"], ad["facts"]["claims"], quebec)[0] == []
    english_lines_only, _ = run("Obtenez 300 $. Conditions apply. Unsubscribe", [], quebec)
    assert keys(english_lines_only) == ["brand.required_footer", "regional.ca.email_consent"]


def test_typographic_apostrophes_do_not_hide_a_required_line():
    quebec = ctx(team="quebec", region="CA-QC", language="fr", channel="radio", budget=None)
    findings, _ = run("Des conditions s’appliquent.", [], quebec)
    assert "brand.required_footer" not in keys(findings)


def test_intro_rate_claim_against_an_offer_without_one():
    claims = [{"type": "intro_rate", "quote": "0% for 6 months", "values": {"rate_percent": 0, "months": 6}}]
    findings, _ = run("0% for 6 months. Conditions apply.", claims, ctx(channel="social"), "TRC-WINTER-2026")
    assert any(f["evidence"].get("offer_field") == "intro_rate" for f in findings)


def test_retired_clause_never_applies():
    assert "brand.holiday_tagline_2025" not in {c["key"] for c in clauses_for("CA")}
    assert "regional.qc.french_language" not in {c["key"] for c in clauses_for("CA")}
    assert "regional.qc.french_language" in {c["key"] for c in clauses_for("CA-QC")}


def test_quote_guard():
    assert rules.quote_in_text("Guaranteed approval!", RUNNING)
    assert rules.quote_in_text("guaranteed  approval", RUNNING)
    assert not rules.quote_in_text("instant approval", RUNNING)
    assert not rules.quote_in_text("", RUNNING)


def test_ensure_required_lines_appends_only_what_is_missing():
    code_clauses = [c for c in clauses_for("CA") if c.get("rule")]
    fixed = rules.ensure_required_lines("Earn $300 cash back. Conditions apply.", ctx(), code_clauses)
    assert fixed.count("Conditions apply.") == 1
    assert fixed.endswith("Unsubscribe: tamarack.test/unsubscribe")
    assert run(fixed, [], ctx())[0] == []
