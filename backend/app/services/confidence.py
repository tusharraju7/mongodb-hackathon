"""Confidence, verdict and route. Arithmetic over evidence; the model never supplies a number.

The score measures how strong the evidence is. It is not a calibrated probability, and the weights
are starting values. Confidence can only make a route stricter.
"""
from __future__ import annotations

from typing import Optional

HIGH, MEDIUM = 80, 50
MODEL_CAP = 95
MIN_SIMILARITY = 0.45  # cosine; below this a similarity match does not count as cover for a claim

CLAIM_LABELS = {
    "approval": "approval",
    "intro_rate": "introductory-rate",
    "rewards_bonus": "bonus",
    "annual_fee": "annual-fee",
    "superlative": "superlative",
    "testimonial": "testimonial",
    "other": "other",
}


def band(score: int) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


def input_quality(modality: str, fine_print_legible: Optional[bool] = None) -> tuple[float, str]:
    if modality == "audio":
        return 0.90, "Transcribed from audio (input quality 0.90)"
    if modality == "image":
        if fine_print_legible is False:
            return 0.60, "Read from an image with hard-to-read fine print (input quality 0.60)"
        return 0.80, "Read from an image (input quality 0.80)"
    if modality == "video":
        # Speech is transcribed and only a few frames are read, so something on screen may be missed.
        return 0.75, "Transcribed from a video and read from sampled frames (input quality 0.75)"
    return 1.00, "The ad was submitted as typed text"


def _conf(score: float, reasons: list[str]) -> dict:
    s = max(0, min(100, int(round(score))))
    return {"score": s, "band": band(s), "reasons": reasons}


def score_finding(
    finding: dict,
    *,
    quality: float,
    quality_reason: str,
    quote_verified: bool,
    mandatory_types: Optional[list[str]] = None,
    applies_to_all: bool = False,
    from_similarity: bool = False,
    standing_instruction: bool = False,
    past_verdict_agrees: bool = False,
) -> dict:
    """Score one finding.

    A clause is mandatory, worth +20, in two ways: it is tied to a claim type the ad makes
    (`mandatory_types`), or it has no claim type and so applies to every ad in scope (`applies_to_all`).
    """
    reasons: list[str] = []
    if finding["basis"] == "code":
        score = 100.0
        reasons.append(
            "Found by a direct comparison with the offer record" if finding["source"] == "offer" else "Found by a deterministic check in code"
        )
    else:
        score = 55.0
        if mandatory_types:
            score += 20
            label = CLAIM_LABELS.get(mandatory_types[0], mandatory_types[0])
            reasons.append(f"Clause is mandatory for {label} claims")
        elif applies_to_all:
            score += 20
            reasons.append("Clause applies to every ad in this region and product")
        elif standing_instruction:
            score += 20
            reasons.append("Rests on a standing instruction for this team")
        elif from_similarity:
            score += 10
            reasons.append("Clause was matched to the ad by similarity search")
        else:
            reasons.append("Rests on a past verdict, not on a standing rule")
        if quote_verified:
            score += 10
            reasons.append("Quote found word for word in the ad")
        certainty = finding.get("certainty") or "likely"
        if certainty == "clear":
            score += 10
            reasons.append("The judge rated the conflict clear")
        elif certainty == "unclear":
            score -= 20
            reasons.append("The judge was unsure about this finding")
        else:
            reasons.append("The judge rated the conflict likely")
        if past_verdict_agrees:
            score += 5
            reasons.append("A past verdict on a similar ad agrees")
        score = min(score, MODEL_CAP)
    if quality < 1.0:
        reasons.append(quality_reason)
    return _conf(score * quality, reasons)


def base_verdict(violations: list[dict], missing_inputs: list[str]) -> tuple[str, str, str]:
    """The business rule: findings decide the route. A similarity score never does."""
    if missing_inputs:
        return "blocked", "human_review", "Missing evidence: " + ", ".join(missing_inputs)
    # A finding the judge labelled unclear never rejects an ad on its own. It keeps the ad from
    # passing and sends it to a person, who decides.
    firm = [v for v in violations if v.get("certainty") != "unclear"]
    material = [v for v in firm if v["materiality"] == "material" or v["source"] == "offer"]
    if material:
        kinds = []
        if any(v["source"] == "offer" for v in material):
            kinds.append("offer mismatch")
        if any(v["source"] != "offer" for v in material):
            kinds.append("material policy conflict")
        return "blocked", "human_review", "Material finding: " + " and ".join(kinds)
    if len(firm) < len(violations):
        return "needs_changes", "human_review", "A finding is unclear and needs a person to decide"
    if any(v["materiality"] == "disclosure" for v in violations):
        return "needs_changes", "draft_correction", "Only missing disclosures, each with an approved fix"
    if violations:
        return "needs_changes", "auto_correct", "Only formatting or brand wording"
    return "pass", "none", "No findings"


def claim_coverage(claims: list[dict], consulted: list[dict], best_similarity: dict[int, float]) -> tuple[float, int]:
    """Share of claims that had an applicable clause to be checked against. Returns (coverage, uncovered)."""
    if not claims:
        return 1.0, 0
    covered = 0
    for i, claim in enumerate(claims):
        has_mandatory = any(claim["type"] in (c.get("claim_types") or []) for c in consulted)
        if has_mandatory or best_similarity.get(i, 0.0) >= MIN_SIMILARITY:
            covered += 1
    return covered / len(claims), len(claims) - covered


def verdict_confidence(
    verdict: str,
    violations: list[dict],
    missing_inputs: list[str],
    *,
    quality: float,
    quality_reason: str,
    claims: list[dict],
    coverage: float,
    uncovered: int,
    complete: bool = False,
) -> dict:
    """`complete` means every applicable policy clause was in front of the judge, so no claim went unchecked."""
    if missing_inputs:
        return _conf(0, ["The ad could not be checked: " + ", ".join(missing_inputs)])
    if verdict == "pass" and complete:
        return _conf(100 * quality, [quality_reason, "Every policy clause that applies to this ad was checked"])
    if verdict == "pass":
        score = 100 * quality * coverage
        reasons = [quality_reason]
        if claims:
            reasons.append(
                f"All {len(claims)} claims had an applicable policy to be checked against"
                if uncovered == 0
                else f"{uncovered} of {len(claims)} claims had no applicable policy"
            )
        else:
            reasons.append("The ad makes no checkable claims")
        if any(c["type"] == "other" for c in claims):
            score -= 10
            reasons.append("At least one claim did not fit a known claim type")
        return _conf(score, reasons)
    # Not a pass: one solid deciding finding is enough.
    if verdict == "blocked":
        deciding = [v for v in violations if (v["materiality"] == "material" or v["source"] == "offer") and v.get("certainty") != "unclear"]
    else:
        deciding = [v for v in violations if v["materiality"] == "disclosure"] or violations
    strongest = max(deciding, key=lambda v: v["confidence"]["score"])
    reasons = [f"Strongest deciding finding: {strongest.get('fundamental_key') or 'team instruction'} ({strongest['confidence']['score']})"]
    reasons += strongest["confidence"]["reasons"][:2]
    return _conf(strongest["confidence"]["score"], reasons)


def escalate(verdict: str, route: str, reason: str, confidence: dict, violations: list[dict]) -> tuple[str, str]:
    """Stricter only: an unclear finding, or a pass that is not high confidence, goes to a human."""
    if route == "human_review":
        return route, reason
    if any(v.get("certainty") == "unclear" for v in violations):
        return "human_review", reason + "; escalated because a finding is unclear"
    if verdict == "pass" and confidence["band"] != "high":
        return "human_review", f"Pass at {confidence['score']} confidence, below the bar of {HIGH}"
    return route, reason
