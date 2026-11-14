"""Confidence arithmetic, verdict and route. No network, no database."""
from app.services import confidence as conf

TEXT = conf.input_quality("text")
IMAGE = conf.input_quality("image")
AUDIO = conf.input_quality("audio")


def model_finding(**over) -> dict:
    base = {"source": "fundamental", "basis": "model", "certainty": "clear", "materiality": "material", "fundamental_key": "credit.approval_claims", "quote": "Guaranteed approval!"}
    return {**base, **over}


def code_finding(**over) -> dict:
    base = {"source": "offer", "basis": "code", "materiality": "material", "fundamental_key": "policy.offer_accuracy", "quote": "0% interest for 12 months"}
    return {**base, **over}


def score(finding, quality=TEXT, **kw):
    return conf.score_finding(finding, quality=quality[0], quality_reason=quality[1], **kw)


def test_worked_example_approval_finding_is_95_on_text_and_76_on_an_image():
    kw = dict(quote_verified=True, mandatory_types=["approval"], past_verdict_agrees=True)
    on_text = score(model_finding(), **kw)
    assert on_text["score"] == 95 and on_text["band"] == "high"
    assert "Clause is mandatory for approval claims" in on_text["reasons"]
    on_image = score(model_finding(), IMAGE, **kw)
    assert on_image["score"] == 76 and on_image["band"] == "medium"
    assert any("image" in r for r in on_image["reasons"])


def test_code_finding_is_100_on_text_and_90_on_a_transcript():
    assert score(code_finding(), quote_verified=True)["score"] == 100
    assert score(code_finding(), AUDIO, quote_verified=True)["score"] == 90


def test_model_finding_never_exceeds_95():
    assert score(model_finding(), quote_verified=True, mandatory_types=["approval"], past_verdict_agrees=True)["score"] <= 95


def test_weaker_evidence_scores_lower():
    missing_disclosure = score(model_finding(quote=""), quote_verified=False, mandatory_types=["intro_rate"])
    assert missing_disclosure["score"] == 85
    similarity_likely = score(model_finding(certainty="likely"), quote_verified=False, from_similarity=True)
    assert similarity_likely["score"] == 65 and similarity_likely["band"] == "medium"
    unclear = score(model_finding(certainty="unclear"), quote_verified=False, from_similarity=True)
    assert unclear["score"] == 45 and unclear["band"] == "low"


def test_clause_that_applies_to_every_ad_counts_as_mandatory():
    french = score(model_finding(fundamental_key="regional.qc.french_language", quote=""), quote_verified=False, applies_to_all=True)
    assert french["score"] == 85 and french["band"] == "high"
    assert "Clause applies to every ad in this region and product" in french["reasons"]


def test_hard_to_read_image_is_penalised_more():
    q = conf.input_quality("image", fine_print_legible=False)
    assert q[0] == 0.60
    assert score(code_finding(), q, quote_verified=True)["score"] == 60


def with_conf(finding, **kw):
    finding = dict(finding)
    finding["confidence"] = score(finding, **kw)
    return finding


def test_material_finding_blocks_and_goes_to_a_human():
    v = [with_conf(code_finding(), quote_verified=True), with_conf(model_finding(materiality="disclosure", quote=""), quote_verified=False)]
    verdict, route, reason = conf.base_verdict(v, [])
    assert (verdict, route) == ("blocked", "human_review") and "offer mismatch" in reason
    c = conf.verdict_confidence(verdict, v, [], quality=1.0, quality_reason=TEXT[1], claims=[], coverage=1.0, uncovered=0)
    assert c["score"] == 100


def test_only_disclosures_need_changes_and_a_draft_correction():
    v = [with_conf(model_finding(materiality="disclosure", quote=""), quote_verified=False, mandatory_types=["rewards_bonus"])]
    assert conf.base_verdict(v, [])[:2] == ("needs_changes", "draft_correction")


def test_only_formatting_is_auto_correct():
    v = [with_conf(model_finding(materiality="formatting"), quote_verified=True)]
    assert conf.base_verdict(v, [])[:2] == ("needs_changes", "auto_correct")


def test_missing_offer_blocks():
    verdict, route, reason = conf.base_verdict([], ["offer_id"])
    assert (verdict, route) == ("blocked", "human_review") and "offer_id" in reason


def test_clean_text_ad_passes_at_100_and_is_not_escalated():
    claims = [{"type": "intro_rate"}, {"type": "rewards_bonus"}]
    consulted = [{"claim_types": ["intro_rate"]}, {"claim_types": ["rewards_bonus"]}]
    coverage, uncovered = conf.claim_coverage(claims, consulted, {})
    verdict, route, reason = conf.base_verdict([], [])
    c = conf.verdict_confidence(verdict, [], [], quality=1.0, quality_reason=TEXT[1], claims=claims, coverage=coverage, uncovered=uncovered)
    assert (verdict, c["score"]) == ("pass", 100)
    assert conf.escalate(verdict, route, reason, c, [])[0] == "none"


def test_a_pass_below_80_is_escalated_but_stays_a_pass():
    claims = [{"type": "intro_rate"}]
    consulted = [{"claim_types": ["intro_rate"]}]
    coverage, uncovered = conf.claim_coverage(claims, consulted, {})
    verdict, route, reason = conf.base_verdict([], [])
    c = conf.verdict_confidence(verdict, [], [], quality=IMAGE[0] * 0.9, quality_reason=IMAGE[1], claims=claims, coverage=coverage, uncovered=uncovered)
    assert c["score"] == 72 and verdict == "pass"
    route, reason = conf.escalate(verdict, route, reason, c, [])
    assert route == "human_review" and "72" in reason


def test_uncovered_and_untyped_claims_lower_a_pass():
    claims = [{"type": "intro_rate"}, {"type": "other"}]
    consulted = [{"claim_types": ["intro_rate"]}]
    coverage, uncovered = conf.claim_coverage(claims, consulted, {1: 0.2})
    assert (coverage, uncovered) == (0.5, 1)
    c = conf.verdict_confidence("pass", [], [], quality=1.0, quality_reason=TEXT[1], claims=claims, coverage=coverage, uncovered=uncovered)
    assert c["score"] == 40
    covered_by_similarity, _ = conf.claim_coverage(claims, consulted, {1: 0.6})
    assert covered_by_similarity == 1.0


def test_unclear_finding_escalates_a_draft_correction():
    v = [with_conf(model_finding(materiality="disclosure", certainty="unclear", quote=""), quote_verified=False, from_similarity=True)]
    verdict, route, reason = conf.base_verdict(v, [])
    c = conf.verdict_confidence(verdict, v, [], quality=1.0, quality_reason=TEXT[1], claims=[], coverage=1.0, uncovered=0)
    assert conf.escalate(verdict, route, reason, c, v)[0] == "human_review"


def test_escalation_never_loosens():
    v = [with_conf(code_finding(), quote_verified=True)]
    verdict, route, reason = conf.base_verdict(v, [])
    c = conf.verdict_confidence(verdict, v, [], quality=1.0, quality_reason=TEXT[1], claims=[], coverage=1.0, uncovered=0)
    assert conf.escalate(verdict, route, reason, c, v) == (route, reason)
