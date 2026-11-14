# Credit-card ad review: embeddings, policy retrieval, and human review

Let’s review this fictional credit-card ad:

> **“Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cashback. Apply today.”**

The policies and scores below are illustrative—not actual legal requirements or measured model outputs.

## 1. Prepare and embed the policies

Your compliance team supplies approved policies. Split them into meaningful clauses, preserving conditions and exceptions.

| Clause | Fictional internal policy |
| --- | --- |
| `P-01` | Do not promise guaranteed approval when eligibility checks apply. |
| `P-02` | An introductory interest-rate claim must include the offer duration and applicable post-promotion APR disclosure. |
| `P-03` | A cashback-bonus claim must disclose its qualifying spending requirement and deadline. |
| `P-04` | Use the approved logo and brand colors. |

Each clause goes through the embedding model:

```text
P-02 text → embedding model → [0.12, -0.38, 0.71, …]
```

MongoDB stores **both the text and the vector**, plus metadata:

```yaml
policy_id: P-02
version: 3
product: credit_card
region: US
status: approved
effective_from: …
effective_to: …
source_section: “Promotional rates, section 4.2”
```

The original text remains the evidence. The vector helps locate it.

## 2. Identify the ad’s claims and context

The agent extracts:

```text
Approval claim: “Guaranteed approval”
Rate claim: “0% interest for 12 months”
Bonus claim: “$300 cashback”
Product: credit card
Region: US
Channel: email
```

The product, region, and channel should come from verified campaign metadata where possible.

Instead of embedding only the entire ad, the agent can also create focused searches:

- “Guaranteed credit-card approval”
- “Introductory interest rate and post-promotion disclosures”
- “Cashback bonus qualification conditions”

These smaller searches help prevent one prominent claim from overshadowing the others.

## 3. Filter, then retrieve by vector similarity

First, MongoDB limits the search to policies applicable to this product, region, date, and approval status.

Then it compares query vectors with policy vectors. For the rate-related query, an illustrative result might be:

| Candidate | Cosine similarity ↑ | Cosine distance ↓ |
| --- | ---: | ---: |
| `P-02`: introductory-rate disclosures | 0.89 | 0.11 |
| `P-03`: bonus conditions | 0.57 | 0.43 |
| `P-04`: brand colors | 0.14 | 0.86 |

These numbers rank relevance. **They do not measure legal risk or determine approval.**

Separately, explicit rules load mandatory policies for each detected claim type—even if vector search misses them.

## 4. Read the actual clauses and offer details

The agent loads the exact retrieved clauses, including referenced exceptions, and the campaign’s approved offer facts:

```text
Approval requires eligibility checks.
Introductory rate: 0% for 12 months.
Post-promotion APR: specified in the approved offer record.
Bonus: $300 after $1,000 qualifying spend within 90 days.
```

It compares those facts with the ad:

| Finding | Evidence | Proposed response |
| --- | --- | --- |
| Unconditional approval promise | “Guaranteed approval” conflicts with `P-01` | Remove the promise |
| Missing post-promotion rate disclosure | Ad states only the introductory rate; `P-02` requires more | Add the approved disclosure |
| Missing bonus conditions | Ad omits spending amount and deadline required by `P-03` | Add the qualifying terms |

If offer facts are missing, the agent requests them rather than inventing an APR or qualification rule.

## 5. Decide whether human review is required

Use an explicit, compliance-approved routing policy:

| Situation | Route |
| --- | --- |
| Only a permitted formatting correction | Automated correction within delegated authority |
| Missing disclosure with an exact approved replacement | Draft correction; route according to approval rules |
| Material claim conflict, policy ambiguity, or missing evidence | Human compliance review |

**This ad needs human review** because it makes a material approval promise that conflicts with the fictional policy. The agent can draft corrections, but cannot release the campaign.

This is a business rule triggered by the finding—not a threshold on cosine similarity.

## 6. Record the decision

MongoDB records the ad version, policy versions, quoted evidence, findings, proposed changes, routing rule, and reviewer decision. Before release, the system checks that the approval still applies to the current ad and policy versions.

The reviewed outcome can become historical memory, while remaining clearly separate from authoritative policy.
