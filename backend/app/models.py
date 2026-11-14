"""Shapes shared across the backend. They mirror docs/CONTRACTS.md section 6."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.profile import claim_types

Role = Literal["manager", "marketer", "sales"]
Team = str      # the teams of the loaded data set; see profile.json
Region = str    # "CA", "CA-ON", "CA-QC", ...
Language = Literal["en", "fr"]
Modality = Literal["text", "audio", "image"]
ClaimType = str  # one of the data set's claim types (profile.json), or "other"
Materiality = Literal["material", "disclosure", "formatting"]
Verdict = Literal["pass", "needs_changes", "blocked"]
Route = Literal["none", "auto_correct", "draft_correction", "human_review"]
Band = Literal["high", "medium", "low"]


def regions_for(ad_region: str) -> list[str]:
    """An ad answers to global clauses and to each level of its own region: CA-ON -> global, CA, CA-ON."""
    parts = (ad_region or "").split("-")
    return ["global"] + ["-".join(parts[: i + 1]) for i in range(len(parts)) if parts[0]]


class Identity(BaseModel):
    user_id: str
    email: str
    name: str = ""
    role: Role
    team: Team


class AdContext(BaseModel):
    """Chosen by the user in the form. The model never guesses these."""

    name: Optional[str] = None
    product: Optional[str] = None       # defaults to the data set's product
    offer_id: Optional[str] = None      # only for data sets that have offer records
    region: Optional[Region] = None     # defaults to the data set's region
    channel: str = "unspecified"        # free text, e.g. "Instagram Stories (paid social)" or "Email (opted-in players)"
    language: Optional[Language] = None
    budget: Optional[dict] = None  # {amount, currency}
    campaign_id: Optional[str] = None
    modality: Modality = "text"
    visual_notes: Optional[str] = None
    fine_print_legible: Optional[bool] = None


class ClaimValues(BaseModel):
    rate_percent: Optional[float] = None
    months: Optional[int] = None
    amount: Optional[float] = None
    fee: Optional[float] = None


class Claim(BaseModel):
    type: ClaimType
    quote: str
    values: Optional[ClaimValues] = None


class Facts(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    cta: Optional[str] = None
    tone: Optional[str] = None
    language: Language = "en"


class Confidence(BaseModel):
    score: int
    band: Band
    reasons: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    policy_excerpt: Optional[str] = None
    offer_field: Optional[str] = None
    ad_value: Optional[Any] = None
    offer_value: Optional[Any] = None
    memory_text: Optional[str] = None


class Violation(BaseModel):
    source: Literal["fundamental", "offer", "memory"]
    basis: Literal["code", "model"]
    certainty: Optional[Literal["clear", "likely", "unclear"]] = None
    fundamental_key: Optional[str] = None
    version: Optional[int] = None
    memory_id: Optional[str] = None
    materiality: Materiality
    quote: str = ""
    explanation: str
    reasoning: str
    evidence: Evidence = Field(default_factory=Evidence)
    fix: str
    confidence: Confidence


class PassedCheck(BaseModel):
    check: str
    detail: Any


class ComplianceReport(BaseModel):
    verdict: Verdict
    decision: Optional[str] = None  # the verdict in the team's own words: approved / approved_with_changes / rejected
    route: Route
    route_reason: str
    summary: str
    confidence: Confidence
    passed_checks: list[PassedCheck] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)  # [{between: [{type, ref, label}], winner: {...}, explanation}]
    channel_class: Optional[str] = None  # public | owned | direct | unknown, decided in code
    prompt_version: Optional[str] = None
    corrected_copy: Optional[str] = None
    corrected_language: Optional[Language] = None  # differs from the ad's when the fix is to change language
    missing_inputs: list[str] = Field(default_factory=list)
    checked_fundamentals: list[dict] = Field(default_factory=list)  # [{key, version}]
    offer_version: Optional[int] = None
    memories_used: list[str] = Field(default_factory=list)
    cached: bool = False


class Grounding(BaseModel):
    band: Band
    sources: list[dict] = Field(default_factory=list)  # [{type: ad|offer, id, version, fields}]
    note: Optional[str] = None


# ---- Shapes the models are asked to return (kept flat and small) ----


class ExtractedClaim(BaseModel):
    type: str = Field(description="The kind of claim: one of the claim types named in the instructions, or 'other' when none fits.")
    quote: str = Field(description="The exact words from the ad, copied character for character.")
    rate_percent: Optional[float] = Field(None, description="Interest rate stated in this claim, as a number.")
    months: Optional[int] = Field(None, description="Duration in months stated in this claim.")
    amount: Optional[float] = Field(None, description="Bonus or cash back amount stated in this claim, in dollars.")
    fee: Optional[float] = Field(None, description="Annual fee stated in this claim, in dollars. 'No annual fee' is 0.")


class Extraction(BaseModel):
    claims: list[ExtractedClaim]
    cta: Optional[str] = Field(None, description="The call to action, in the ad's words, if there is one.")
    tone: str = Field(description="One or two words, for example 'plain', 'calm', 'promotional', 'urgent'.")
    language: Language = Field(description="The language the ad is written or spoken in.")
    description: str = Field(description="One sentence, in the ad's language: what a customer would remember about this ad.")
    summary: str = Field(description="At most 60 words, in English, for an internal reviewer: what the ad offers and on what terms.")

    def facts(self) -> Facts:
        claims = []
        for c in self.claims:
            values = ClaimValues(rate_percent=c.rate_percent, months=c.months, amount=c.amount, fee=c.fee)
            ctype = c.type if c.type in claim_types() else "other"
            claims.append(Claim(type=ctype, quote=c.quote, values=values if values.model_dump(exclude_none=True) else None))
        return Facts(claims=claims, cta=self.cta, tone=self.tone, language=self.language)


class JudgeFinding(BaseModel):
    source: Literal["policy", "memory"] = Field(description="'policy' for a listed policy clause, 'memory' for a listed team memory.")
    ref: str = Field(description="The policy key or the memory id, exactly as listed.")
    quote: str = Field(description="The exact words from the ad that cause the problem. Empty when the problem is something missing from the ad.")
    explanation: str = Field(description="One sentence: what is wrong.")
    reasoning: str = Field(description="At most two sentences: what the ad says, what is required, and why they conflict.")
    fix: str = Field(description="What to change, as a short instruction.")
    certainty: Literal["clear", "likely", "unclear"]
    agrees_with_memory: Optional[str] = Field(None, description="Id of a listed past-verdict memory that settled a similar case the same way, if any.")


class JudgeConflict(BaseModel):
    between: list[str] = Field(description="The clause keys and memory ids that disagree about this ad, exactly as listed. At least two.")
    winner: str = Field(description="The clause key or memory id that prevails under the ranking of sources.")
    explanation: str = Field(description="One sentence: what each side says and why the winner prevails.")


class JudgeOutput(BaseModel):
    findings: list[JudgeFinding]
    conflicts: list[JudgeConflict] = Field(default_factory=list, description="Places where the sources disagree about this ad. Empty when none do.")
    summary: str = Field(description="At most three plain sentences for the marketer: the outcome and the main reasons.")
    corrected_copy: str = Field(description="The complete ad rewritten so that it has no findings. The ad unchanged if nothing needs fixing.")
    corrected_copy_language: Language = Field(description="The language the corrected copy is written in.")


class RepairOutput(BaseModel):
    corrected_copy: str
