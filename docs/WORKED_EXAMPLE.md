# Worked example: reviewing a credit card ad

One ad, followed from policy document to release. This builds on the credit card example drafted on the `Chelsea-setup` branch, moved to a Canadian setting and mapped to the collections and flows in this repo.

Everything here is fictional. Tamarack Bank and the Tamarack Cashback Card do not exist. The policies are invented internal policy, loosely modelled on Canadian practice; they are not legal requirements. Similarity scores are illustrative, not measured.

## The ad

Submitted by a marketer on the national team:

> **"Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."**

Submitted with it (chosen in the form, not guessed by the model):

```json
{ "product": "credit_card", "offer_id": "TCB-FALL-2026", "region": "CA",
  "channel": "email", "language": "en", "budget": { "amount": 20000, "currency": "CAD" } }
```

### Three ways to submit it, one flow

The marketer can paste the campaign text, upload a voice recording, or upload an image. Each is turned into text once, and from that point every step below is the same.

| Uploaded as | First step | What the review receives |
|---|---|---|
| Campaign text | None | The text as typed |
| Voice recording (mp3, wav, m4a) | ElevenLabs Scribe transcribes it | The transcript |
| Image (png, jpg) | A vision model reads it | All the text on the image, fine print included, plus a note on what is shown |

A voice recording of the ad comes back as:

```json
{ "text": "Guaranteed approval! Enjoy zero percent interest for twelve months and earn three hundred dollars cash back. Apply today." }
```

A banner of the ad comes back as:

```json
{
  "text": "Guaranteed approval! 0% interest for 12 months. Earn $300 cash back. Apply today.",
  "visual_notes": "Dark green banner. Headline 'Guaranteed approval!' in large type. A picture of the card. No fine print anywhere on the image. No people shown."
}
```

What differs by form, and only this:

- **The file is kept.** The recording or image is stored in MongoDB (GridFS) and attached to the ad, so it can be played or shown later. The extracted text is stored beside it and is what gets reviewed.
- **Visual notes join the review** for images. "No fine print anywhere" supports the missing-disclosure findings; a recognisable person would bring in the consent clause.
- **Confidence is lower** for a transcript (× 0.90) or an image reading (× 0.80), because the text could have been misheard or misread.
- **The regenerated version matches the form:** corrected text, a new voice recording, or a new banner.

The steps below follow the text submission. Where audio or image would differ, it is noted.

## 1. Policies are stored as clauses

The compliance team's policy document is split into clauses. One clause = one thing an ad can get wrong. Each clause keeps its conditions, a pointer back to the source section, and a lifetime.

```json
{
  "key": "credit.intro_rate_disclosure",
  "category": "legal",
  "region": "CA",
  "product": "credit_card",
  "title": "Introductory interest rate claims",
  "text": "An ad that states an introductory interest rate must also state how long it lasts and the annual interest rate that applies afterwards, with equal prominence.",
  "summary": "Intro rate claims must state the duration and the rate that applies afterwards.",
  "source_section": "Card Marketing Standard, section 4.2",
  "claim_types": ["intro_rate"],
  "materiality": "disclosure",
  "approved_fix": {
    "en": "{intro_rate}% interest on purchases for {intro_months} months, then {standard_rate}%.",
    "fr": "Taux d'intérêt de {intro_rate} % sur les achats pendant {intro_months} mois, puis {standard_rate} %."
  },
  "status": "approved",
  "effective_from": "2026-06-01T00:00:00Z",
  "effective_to": null,
  "version": 3,
  "embedding": [0.0213, -0.0458, 0.0127, "... 1,024 numbers in total"]
}
```

The text is the evidence. The embedding only helps find it. `claim_types` means this clause is always loaded when an ad makes an introductory-rate claim, whether or not the search finds it.

## 2. The approved offer is a separate record

What the bank has actually approved for this promotion lives in `offers`. The agent never invents a rate or a condition; if the offer record is missing, it asks for it and stops.

```json
{
  "_id": "TCB-FALL-2026",
  "product": "credit_card",
  "card_name": "Tamarack Cashback Card",
  "card_name_fr": "Carte Remises Tamarack",
  "teams": ["national", "quebec"],
  "intro_rate": { "rate_percent": 0, "months": 10, "applies_to": "purchases" },
  "standard_rate_percent": 20.99,
  "bonus": { "amount": 300, "currency": "CAD", "qualifying_spend": 1500, "window_days": 90 },
  "annual_fee": 0,
  "eligibility": "Subject to credit approval",
  "valid_from": "2026-09-01T00:00:00Z", "valid_to": "2026-12-31T23:59:59Z",
  "version": 1
}
```

This policy clause and this offer are in the seed data (`backend/seed/fundamentals.json`, `backend/seed/offers.json`), so the example can be run as written.

## 3. The agent extracts the ad's claims

One call on the fast model. The same output later serves questions about the ad (UC5), so it is paid for once.

```json
{
  "claims": [
    { "type": "approval",      "quote": "Guaranteed approval!" },
    { "type": "intro_rate",    "quote": "0% interest for 12 months", "values": { "rate_percent": 0, "months": 12 } },
    { "type": "rewards_bonus", "quote": "earn $300 cash back",       "values": { "amount": 300 } }
  ],
  "cta": "Apply today",
  "language": "en"
}
```

## 4. Checks that need no model

Done in code, before any policy search:

| Check | Result |
|---|---|
| Budget against the national team cap | CAD 20,000 is under the cap. Pass |
| Banned terms (competitor names) | None. Pass |
| Required lines for an email card ad | "Conditions apply." missing. Unsubscribe line missing |
| Claim values against the offer record | Ad says 12 months, offer says 10. **Mismatch** |

The mismatch is the kind of error a policy search alone cannot catch: no rule says "ten months", the offer record does.

## 5. Finding the relevant clauses, one claim at a time

Searching with the whole ad lets the loudest claim crowd out the others. The agent searches once per claim instead, with all claims embedded in a single Voyage call.

Before comparing vectors, Atlas filters to clauses that can apply at all: `product` is `credit_card` or `all`, `region` is `global` or `CA`, `status` is `approved`, and today falls inside the effective dates.

Illustrative result for the claim "0% interest for 12 months":

| Clause | Similarity |
|---|---:|
| `credit.intro_rate_disclosure` | 0.89 |
| `credit.bonus_conditions` | 0.57 |
| `brand.naming_and_logo` | 0.14 |

The score ranks relevance. It does not measure risk and never decides approval.

Then the mandatory clauses for each claim type are added by a plain lookup on `claim_types`, in case the search missed one. For this ad: `credit.approval_claims`, `credit.intro_rate_disclosure`, `credit.bonus_conditions`, `policy.offer_accuracy`.

## 6. Memory is consulted, and kept separate from policy

The agent recalls up to three memories for the national team: standing instructions from the manager and past verdicts on similar ads. For example:

> Episodic, 12 days old: "A national email ad was blocked for 'instant approval'. The version saying 'Subject to credit approval' was approved."

Memory can add a team instruction or show how a similar case was settled. It cannot waive a policy clause. Verdicts cite a policy key and version, or a memory id, so a reviewer can always tell which one drove a finding.

## 7. The verdict

The main model reads the ad, the extracted claims, the offer record, the clause summaries and the memories, and returns structured findings. Hard-rule results from step 4 are merged in. The confidence, reasoning and evidence that accompany each finding are shown in the next section, and left out here to keep the findings readable.

```json
{
  "verdict": "blocked",
  "route": "human_review",
  "violations": [
    { "source": "fundamental", "fundamental_key": "credit.approval_claims", "version": 2,
      "materiality": "material", "quote": "Guaranteed approval!",
      "explanation": "Approval depends on a credit check, so it cannot be promised.",
      "fix": "Remove the promise and add: Subject to credit approval." },
    { "source": "offer", "fundamental_key": "policy.offer_accuracy", "version": 1,
      "materiality": "material", "quote": "0% interest for 12 months",
      "explanation": "The approved offer TCB-FALL-2026 is 0% for 10 months, not 12.",
      "fix": "Change 12 months to 10 months." },
    { "source": "fundamental", "fundamental_key": "credit.intro_rate_disclosure", "version": 3,
      "materiality": "disclosure", "quote": "0% interest for 12 months",
      "explanation": "The rate that applies after the introductory period is not stated.",
      "fix": "0% interest on purchases for 10 months, then 20.99%." },
    { "source": "fundamental", "fundamental_key": "credit.bonus_conditions", "version": 1,
      "materiality": "disclosure", "quote": "earn $300 cash back",
      "explanation": "The spending requirement and deadline are not stated.",
      "fix": "Earn $300 cash back after $1,500 in purchases in your first 3 months." },
    { "source": "fundamental", "fundamental_key": "regional.ca.email_consent", "version": 1,
      "materiality": "disclosure", "quote": "",
      "explanation": "Email ads must carry an unsubscribe line.",
      "fix": "Add the standard unsubscribe line." },
    { "source": "fundamental", "fundamental_key": "brand.required_footer", "version": 1,
      "materiality": "disclosure", "quote": "",
      "explanation": "Card ads must carry the line: Conditions apply.",
      "fix": "Add: Conditions apply." }
  ],
  "corrected_copy": "Enjoy 0% interest on purchases for 10 months, then 20.99%. Earn $300 cash back after $1,500 in purchases in your first 3 months. Subject to credit approval. Conditions apply. Apply today. Unsubscribe: tamarack.test/unsubscribe",
  "checked_fundamentals": [
    { "key": "credit.approval_claims", "version": 2 },
    { "key": "credit.intro_rate_disclosure", "version": 3 },
    { "key": "credit.bonus_conditions", "version": 1 },
    { "key": "policy.offer_accuracy", "version": 1 },
    { "key": "regional.ca.email_consent", "version": 1 },
    { "key": "brand.required_footer", "version": 1 }
  ],
  "memories_used": ["6741c0aa0000000000000012"],
  "cached": false
}
```

## 8. Confidence, feedback and reasoning

The report opens with a summary and a confidence score for the verdict:

```json
{
  "verdict": "blocked",
  "summary": "This ad cannot run as written. It promises approval, which depends on a credit check, and it states a 12-month introductory rate where the approved offer is 10 months. Four disclosures are also missing; corrected copy is provided.",
  "confidence": {
    "score": 100,
    "band": "high",
    "reasons": [
      "The offer mismatch was found by a direct comparison with the offer record",
      "The ad was submitted as typed text"
    ]
  },
  "route": "human_review",
  "route_reason": "Material conflict: approval promise and offer mismatch",
  "passed_checks": [
    { "check": "budget_cap", "detail": "CAD 20,000 is within the national team cap" },
    { "check": "banned_terms", "detail": "No competitor names" },
    { "check": "offer_match.bonus_amount", "detail": "$300 matches the offer" }
  ]
}
```

Each finding then carries its own reasoning, evidence and confidence. A finding from a check in code:

```json
{
  "source": "offer", "fundamental_key": "policy.offer_accuracy", "version": 1,
  "basis": "code", "materiality": "material",
  "quote": "0% interest for 12 months",
  "reasoning": "The ad states the introductory rate lasts 12 months. The approved offer TCB-FALL-2026 sets it at 10 months, so the ad overstates the offer.",
  "evidence": { "offer_field": "intro_rate.months", "ad_value": 12, "offer_value": 10 },
  "fix": "Change 12 months to 10 months.",
  "confidence": { "score": 100, "band": "high",
                  "reasons": ["Found by a direct comparison with the offer record"] }
}
```

A finding judged by the model:

```json
{
  "source": "fundamental", "fundamental_key": "credit.approval_claims", "version": 2,
  "basis": "model", "certainty": "clear", "materiality": "material",
  "quote": "Guaranteed approval!",
  "reasoning": "The ad promises that every applicant will be approved. The offer is subject to credit approval, and the policy forbids promising approval when eligibility checks apply.",
  "evidence": { "policy_excerpt": "Do not promise guaranteed or instant approval when eligibility checks apply." },
  "fix": "Remove the promise and add: Subject to credit approval.",
  "confidence": { "score": 95, "band": "high",
                  "reasons": ["Clause is mandatory for approval claims",
                              "Quote found word for word in the ad",
                              "The judge rated the conflict clear",
                              "A past verdict on a similar ad agrees"] }
}
```

How the 95 was reached: a model finding starts at 55; +20 because the clause is mandatory for approval claims; +10 because the quote is in the ad word for word; +10 because the judge called it clear; +5 because the recalled past verdict agrees. That is 100, capped at 95 for anything the model judged, then multiplied by 1.00 because the ad was typed text.

The same ad uploaded as a banner image would score 76 on this finding (95 × 0.80), which is medium, because the text was read from an image and could have been misread.

Three things to keep in mind:

- The number is arithmetic on the evidence, done in code. The model is never asked how confident it is; it only labels its findings clear, likely or unclear.
- It measures how strong the evidence is. It is not the probability that the verdict is right, and the weights are starting values, not calibrated ones.
- If the model quotes words that are not in the ad, the finding is thrown out before scoring.

## 9. Routing is a business rule, not a score

Decided in code from the findings:

| Findings include | Route | Verdict |
|---|---|---|
| A material conflict, an offer mismatch, or missing evidence (no offer record) | `human_review` | `blocked` |
| Only missing disclosures that have an approved fix | `draft_correction` | `needs_changes` |
| Only formatting or brand wording | `auto_correct` | `needs_changes` |
| Nothing | `none` | `pass` |

Confidence can add to this, in one direction only: a finding the judge labelled unclear, or a pass whose confidence is not high, also goes to human review. It never makes a route more lenient.

This ad promises approval and contradicts the offer record, so it goes to human review. The agent drafts the corrected copy; it cannot approve or release anything.

In this build the route is recorded and shown, and every ad still needs a manager's approval before release.

## 10. Regenerating a compliant version

The report offers **Regenerate compliant version**. Pressing it is a gated action of its own (`asset.regenerate`):

1. The corrected copy from the report is reviewed with the same checks as any ad. No new copy is written unless that review fails, in which case there is one repair attempt.
2. If the copy still does not pass, nothing is produced and the remaining findings go to human review.
3. If it passes, it is rendered in the ad's own form:

| The ad was | The regenerated version is |
|---|---|
| Text | The corrected copy |
| Audio | A new recording of the corrected script, from ElevenLabs text-to-speech with a stock voice |
| Image | The corrected copy laid out on the brand template, rendered in code so rates and fine print are exact |

4. It is saved as version 2 of the ad, marked as regenerated from version 1, with its passing report, waiting for review.

The check comes before the rendering, so no audio or image is ever produced from copy that has not passed. A regenerated file is a new rendering, not an edit of the original recording or artwork.

## 11. Approval and release

Version 2 has passed review. The manager approves it, and the approval is tied to exactly what was reviewed:

```json
{
  "approval": {
    "by": "manager.national@tamarack.test",
    "at": "2026-11-14T19:20:00Z",
    "ad_version": 2,
    "policy_versions": [
      { "key": "credit.approval_claims", "version": 2 },
      { "key": "credit.intro_rate_disclosure", "version": 3 },
      { "key": "credit.bonus_conditions", "version": 1 },
      { "key": "policy.offer_accuracy", "version": 1 },
      { "key": "regional.ca.email_consent", "version": 1 },
      { "key": "brand.required_footer", "version": 1 }
    ],
    "offer_version": 1
  }
}
```

When someone presses **Release**, the gate re-checks before anything happens:

- Is the ad still at version 2?
- Is every listed policy still at the listed version, still approved and still in effect?
- Is the offer still at version 1 and still valid?

If the compliance team changed `credit.intro_rate_disclosure` to version 4 after the approval, release is refused with "approval is stale: `credit.intro_rate_disclosure` changed from version 3 to 4", the refusal is written to the ledger, and the ad goes back to review.

## 12. What is recorded

For this one review, the ledger holds, under one `run_id`: who submitted it, the allow decision, each step taken, the policy keys and versions consulted, the memory ids used, the verdict, its confidence and route, and the tokens spent. Regeneration, approval and release are separate ledger events with their own actor.

The ad itself is one document in `campaigns`. After the first review of the voice-recording submission it looks like this:

```json
{
  "team": "national", "name": "Fall cashback radio spot",
  "product": "credit_card", "offer_id": "TCB-FALL-2026",
  "region": "CA", "channel": "radio", "language": "en",
  "modality": "audio", "version": 1,
  "text": "Guaranteed approval! Enjoy zero percent interest for twelve months and earn three hundred dollars cash back. Apply today.",
  "assets": [ { "type": "audio", "file_id": "<GridFS id of the uploaded recording>", "mime": "audio/mpeg" } ],
  "facts": { "claims": [
      { "type": "approval", "quote": "Guaranteed approval!" },
      { "type": "intro_rate", "quote": "zero percent interest for twelve months", "values": { "rate_percent": 0, "months": 12 } },
      { "type": "rewards_bonus", "quote": "three hundred dollars cash back", "values": { "amount": 300 } } ],
    "cta": "Apply today", "language": "en" },
  "source": "submitted", "status": "pending_review",
  "compliance": { "verdict": "blocked", "route": "human_review",
                  "confidence": { "score": 90, "band": "high" }, "violations": ["..."] },
  "created_by": "<marketer id>", "run_id": "0b6f3c1e-...", "created_at": "2026-11-14T19:02:11Z"
}
```

Its verdict confidence is 90 rather than 100 because the offer mismatch, a code check worth 100, is multiplied by 0.90 for a transcript. Regenerating adds version 2 with `source: "regenerated"`, `derived_from: 1`, the corrected text and a new audio file.

Two of the ledger events for that review:

```json
{ "ts": "2026-11-14T19:02:09Z", "run_id": "0b6f3c1e-...",
  "actor": { "user_id": "<marketer id>", "email": "marketer.national@tamarack.test", "role": "marketer", "team": "national" },
  "event": "decision", "action": "compliance.check",
  "params": { "modality": "audio", "offer_id": "TCB-FALL-2026", "region": "CA", "channel": "radio" },
  "decision": "allow", "reason": "role marketer holds compliance.check",
  "auth": { "method": "jwt" } }

{ "ts": "2026-11-14T19:02:14Z", "run_id": "0b6f3c1e-...",
  "actor": { "user_id": "<marketer id>", "email": "marketer.national@tamarack.test", "role": "marketer", "team": "national" },
  "event": "outcome", "action": "compliance.check",
  "policy_refs": [ { "key": "credit.approval_claims", "version": 2 }, { "key": "credit.intro_rate_disclosure", "version": 3 },
                   { "key": "credit.bonus_conditions", "version": 1 }, { "key": "policy.offer_accuracy", "version": 1 },
                   { "key": "brand.required_footer", "version": 1 } ],
  "memories_used": ["<id of nat-epi-instant-approval>"],
  "result": { "status": "blocked", "summary": "Blocked: approval promise and offer mismatch. Routed to human review.",
              "confidence": 90, "ref": { "collection": "campaigns", "id": "<ad id>" } },
  "undo": { "type": "campaign.rollback", "ref": "<ad id>" },
  "auth": { "method": "jwt" }, "tokens": { "in": 1840, "out": 620 } }
```

The decision is written before the transcription starts; the outcome after the verdict. Token counts are illustrative.

The outcome also becomes an episodic memory for the national team, expiring in 30 days:

> "An email ad for TCB-FALL-2026 was blocked for 'Guaranteed approval' and for stating 12 months against an approved 10. The corrected version was approved."

## 13. Later: a question from sales

A branch advisor asks: *"A customer got an email about $300 cash back on the card. What are the conditions?"*

The agent finds the released ad the advisor is allowed to see, and answers from its stored facts and the offer record: $300 after $1,500 in purchases in the first 3 months; 0% on purchases for 10 months, then 20.99%; subject to credit approval. It returns the ad itself alongside the answer, in its own form: the email text, the radio spot with a player, or the banner image. It does not state any term that is not in the ad or the offer record. The answer names its sources (the ad and version, offer TCB-FALL-2026 version 1) and is marked high confidence because every term came from the offer record. Asked about something neither holds, such as a foreign transaction fee, it says the ad and offer do not cover it.
