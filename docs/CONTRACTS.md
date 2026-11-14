# Contracts

Frozen interfaces between streams. Change this file only in a tiny dedicated PR announced in team chat.

Database: `greenlight` on the shared Atlas Sandbox cluster. Ids are ObjectIds unless stated; over the API they are strings. Timestamps are UTC datetimes.

Scope: UC1 review existing creative (with regenerate, approve and release), UC4 memory updates, UC5 questions about an ad. Ads are text, audio or image, in and out.

Validators, index definitions, creation order and the seed data are in [MONGODB_SETUP.md](MONGODB_SETUP.md). The seed files are in `backend/seed/`. See [FLOWS.md](FLOWS.md) and [WORKED_EXAMPLE.md](WORKED_EXAMPLE.md).

## 1. Identity

```
Identity = { user_id: str, email: str, name: str, role: "manager" | "marketer" | "sales", team: "national" | "quebec" }
```
Built from the JWT by `core/security.py::current_identity`. Never taken from a request body or model output.

## 2. Regions, products, claim types

Ads carry `region: "CA" | "CA-QC"` and `product: "credit_card"`. Policies carry `region: "global" | "CA" | "CA-QC"` and `product: "credit_card" | "all"`.

```python
def regions_for(ad_region: str) -> list[str]
#   "CA"    → ["global", "CA"]
#   "CA-QC" → ["global", "CA", "CA-QC"]

ClaimType = "approval" | "intro_rate" | "rewards_bonus" | "annual_fee" | "superlative" | "testimonial" | "other"
```

## 3. Collections

### `users`
```
{ _id, email (unique), name, role, team, password_hash, created_at }
```

### `policies` — the role permission matrix
```
{ _id: "<role>", actions: ["compliance.check", ...], updated_at }
```

| Action | manager | marketer | sales |
|---|---|---|---|
| `compliance.check` | yes | yes | |
| `campaign.submit` | yes | yes | |
| `asset.regenerate` | yes | yes (own team) | |
| `campaign.approve` | yes | | |
| `campaign.release` | yes | yes (own team) | |
| `campaign.search` | yes | yes | yes (released only) |
| `campaign.ask` | yes | yes | yes (released only) |
| `fundamentals.read` | yes | yes | |
| `fundamentals.update` | yes + step-up | | |
| `fundamentals.review` | yes | | |
| `memory.read` | yes | yes | |
| `memory.write` | yes (team scope needs step-up) | self scope only | |
| `memory.forget` | yes + step-up | own notes only | |
| `run.stop` | yes | own runs | |
| `run.rollback` | yes | | |
| `audit.read` | yes | own runs | |

"Released only", "own team", "self scope" and "own runs" are enforced by query filters in the owning service, in addition to the action check in the gate.

### `fundamentals` — policy clauses (semantic memory)

One document per clause: one thing an ad can get wrong.

```
{ _id, key (unique, e.g. "credit.intro_rate_disclosure"),
  category: "brand" | "company_policy" | "budget" | "regional" | "consent" | "legal",
  region: "global" | "CA" | "CA-QC",
  product: "credit_card" | "all",
  title, text, summary (<= 60 words),
  source_section,                         // where it comes from in the policy document
  claim_types: [ClaimType],               // always loaded when an ad makes a claim of this type
  materiality: "material" | "disclosure" | "formatting",
  approved_fix?: { en: str, fr: str },    // exact approved wording; may use offer placeholders such as {intro_months}
  rule?: { type: "budget_cap", team, max, currency: "CAD" }
       | { type: "banned_terms", terms: [str] }
       | { type: "required_line", channel?: str, lines: { en: str, fr: str } }   // matched in the ad's language
       | { type: "offer_match" },         // claim values must equal the offer record
  status: "approved" | "draft" | "retired",
  effective_from, effective_to: datetime | null,
  version: int, embedding: [float x 1024],
  updated_by: user_id, updated_at }
```

A clause applies to an ad when `product` is the ad's product or `all`, `region` is in `regions_for(ad region)`, `status` is `approved`, and now is within the effective dates.

Seed set. This is fictional internal policy for Tamarack Bank, loosely modelled on Canadian practice. It is illustrative and not legal advice.

| key | category | region | materiality | claim types | hard rule | In one line |
|---|---|---|---|---|---|---|
| `brand.voice_tone` | brand | global | formatting | | | Plain, calm, no pressure or urgency tricks |
| `brand.naming_and_logo` | brand | global | formatting | | | Use the approved product name "Tamarack Cashback Card" |
| `brand.required_footer` | brand | global | disclosure | | `required_line` | Card ads carry "Conditions apply." |
| `policy.offer_accuracy` | company_policy | global | material | intro_rate, rewards_bonus, annual_fee | `offer_match` | Every number in an ad matches the approved offer record |
| `policy.claims_substantiation` | company_policy | global | material | superlative | | No "best", "lowest" or "number one" without evidence on file |
| `policy.competitor_mentions` | company_policy | global | material | | `banned_terms` | Do not name competitors |
| `budget.cap.national` | budget | global | material | | `budget_cap` | Per-campaign cap for the national team, in CAD |
| `budget.cap.quebec` | budget | global | material | | `budget_cap` | Per-campaign cap for the Quebec team, in CAD |
| `credit.approval_claims` | legal | CA | material | approval | | Do not promise guaranteed or instant approval; say "Subject to credit approval" |
| `credit.intro_rate_disclosure` | legal | CA | disclosure | intro_rate | | An intro rate claim states its duration and the rate that applies afterwards |
| `credit.bonus_conditions` | legal | CA | disclosure | rewards_bonus | | A bonus claim states the qualifying spend and the deadline |
| `credit.annual_fee_disclosure` | legal | CA | disclosure | annual_fee | | "No annual fee" only if the offer record says so; otherwise state the fee |
| `credit.responsible_borrowing` | company_policy | CA | material | | | No "free money", no encouragement to carry debt, nothing aimed at minors |
| `regional.ca.email_consent` | regional | CA | disclosure | | `required_line` | Email ads carry an unsubscribe line |
| `regional.qc.french_language` | regional | CA-QC | material | | | Quebec ads are in French, or French is clearly predominant |
| `regional.qc.credit_terms` | regional | CA-QC | disclosure | intro_rate | | A Quebec ad that mentions any credit term states the credit rate with equal prominence |
| `consent.testimonials_and_likeness` | consent | global | material | testimonial | | No real person's name, voice, likeness or testimonial without written consent on file |

### `fundamentals_versions`
```
{ _id, fundamental_id, key, version, snapshot: <full previous document without embedding>,
  replaced_by: user_id, replaced_at, reason }
```

### `offers` — approved promotion terms (read-only reference data, seeded)
```
{ _id: "TCB-FALL-2026", product: "credit_card", card_name, card_name_fr, teams: ["national", "quebec"],
  intro_rate: { rate_percent, months, applies_to: "purchases" } | null,
  standard_rate_percent,
  bonus: { amount, currency: "CAD", qualifying_spend, window_days } | null,
  annual_fee, eligibility,
  valid_from, valid_to, version: int }
```
The agent never states a rate, fee or condition that is not in the ad or the offer record. No offer record → the review stops and asks for one.

### `ledger` — append-only audit events
```
{ _id, ts, run_id, thread_id,
  actor: { user_id, email, role, team },
  event: "decision" | "outcome" | "stop" | "rollback",
  action: "<action from the permission matrix>",
  params: { ...redacted summary, never passwords or raw audio... },
  decision?: "allow" | "deny", reason?: str,
  policy_refs?: [ { key, version } ],
  memories_used?: [ memory_id ],
  result?: { status: "ok" | "blocked" | "error", summary, confidence?: int, ref?: { collection, id } },
  undo?: { type: "fundamental.restore" | "memory.revert" | "campaign.rollback", ref },
  auth: { method: "jwt" | "jwt+password" },
  tokens?: { in, out } }
```
Validator (`$jsonSchema`): `ts`, `run_id`, `actor.user_id`, `actor.role`, `event`, `action`, `auth.method` are required; `event` and `decision` are enums. Application code only ever inserts into this collection. Database-level enforcement (an insert-only role) is a P2 task; until it lands, describe the ledger as append-only by convention.

### `runs`
```
{ _id: run_id (uuid string, generated by the client), thread_id, actor, input,
  intent: "review" | "regenerate" | "memory_update" | "ask" | "approve" | "release",
  status: "running" | "completed" | "blocked" | "needs_input" | "denied"
        | "stop_requested" | "stopped" | "rolled_back" | "error",
  memory_enabled: bool, memories_used: [memory_id], tokens: { in, out },
  started_at, ended_at }
```

### `campaigns` — the ad library
```
{ _id, team, name, product: "credit_card", offer_id,
  region: "CA" | "CA-QC", channel: "email" | "radio" | "podcast" | "social" | "display",
  language: "en" | "fr", budget: { amount, currency: "CAD" },
  modality: "text" | "audio" | "image",
  version: int,                       // increments whenever the text changes; clears `approval`
  text (ad copy, the transcript of an audio ad, or all text read from an image ad),
  visual_notes?: str,                 // image ads: what is shown (people, logos, legibility of fine print)
  summary (<= 60 words), description (what a customer would remember; this is what search matches),
  facts: { claims: [ { type: ClaimType, quote, values? } ], cta, tone, language },
  assets: [ { type: "audio" | "image", file_id, mime } ],   // audio/mpeg, image/png, image/jpeg
  source: "seed" | "submitted" | "regenerated",
  derived_from?: int,                 // regenerated versions: the version they correct
  status: "pending_review" | "approved" | "released" | "rejected" | "rolled_back",
  compliance: ComplianceReport + { checked_at, cache_key },
  approval?: { by: user_id, at, ad_version, policy_versions: [ { key, version } ],
               offer_version, run_id },
  embedding: [float x 1024],          // of description + summary
  ref?: str,                          // seeded ads only: stable slug used for upserts
  created_by, rejected_by?, review_feedback?, run_id, created_at, released_at? }
```

### `memories`
```
{ _id, kind: "semantic" | "episodic" | "procedural", text,
  scope: { team, user_id: str | null },        // null = whole team
  visibility_roles: ["manager", "marketer"],   // roles allowed to recall it
  embedding: [float x 1024],
  status: "active" | "superseded" | "forgotten",
  supersedes?: memory_id,
  expires_at: datetime | null,
  source: { run_id, type: "agent" | "manager_instruction" | "review_feedback" | "user_note" },
  created_by, created_at, use_count: int, last_used_at }
```
Memory never overrides a policy clause. It can add a team instruction or show how a similar case was settled.

### Others
- `checkpoints`, `checkpoint_writes` — LangGraph `MongoDBSaver`.
- `fs.files`, `fs.chunks` — GridFS audio and images.

## 4. Indexes

Vector indexes (type `vectorSearch`, cosine, 1024 dimensions, path `embedding`):

| Index | Collection | Filter fields |
|---|---|---|
| `fundamentals_vec` | `fundamentals` | `category`, `region`, `product`, `status` |
| `campaigns_vec` | `campaigns` | `status`, `team` |
| `memories_vec` | `memories` | `kind`, `status`, `scope.team`, `visibility_roles` |

```json
{ "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
    { "type": "filter", "path": "status" },
    { "type": "filter", "path": "team" }
] }
```

Regular indexes: `users.email` unique; `fundamentals.key` unique; `fundamentals.claim_types`; `ledger {run_id: 1, ts: 1}`; `ledger {"actor.user_id": 1, ts: -1}`; `memories.expires_at` TTL with `expireAfterSeconds: 0`; `campaigns {team: 1, status: 1, created_at: -1}`.

## 5. Service signatures (cross-stream calls)

```python
# core/gate.py  (A)
def guarded(identity, action: str, params: dict, run_id: str, fn, *,
            undo: dict | None = None, policy_refs: list | None = None,
            memories_used: list | None = None, auth_method: str = "jwt") -> Any
class Denied(Exception): ...        # router maps to 403
class RunStopped(Exception): ...    # router maps to run status "stopped"

# core/security.py  (A)
def current_identity(...) -> Identity               # FastAPI dependency
def verify_password(identity, password: str) -> bool  # step-up

# core/embeddings.py  (C)
def embed_documents(texts: list[str]) -> list[list[float]]
def embed_queries(texts: list[str]) -> list[list[float]]    # one batched call

# core/llm.py  (B)
def main_model()   # compliance verdict only
def fast_model()   # router, claim extraction, image reading, Q&A, drafting (must accept image input)

# services/compliance.py  (B)
def extract_claims(text: str) -> Facts
def check(text: str, ctx: dict, identity, run_id: str, *, use_memory: bool = True) -> ComplianceReport
#   ctx = { product, offer_id, region, channel, language?, budget?: {amount, currency},
#           campaign_id?, visual_notes? }
def regenerate(identity, run_id: str, campaign_id: str) -> RegenerateResult
#   corrected copy → check → at most one repair → check → render via services/media → campaigns.submit.
#   Fail closed: if the copy does not pass, nothing is rendered or saved.

# services/fundamentals.py  (A)
def list_all(identity) -> list[Fundamental]
def retrieve(query_vectors: list, *, regions: list[str], product: str, k_per_query: int = 2) -> list[FundamentalSummary]
def mandatory(claim_types: list[str], *, regions: list[str], product: str) -> list[FundamentalSummary]
def hard_rules(*, regions: list[str], product: str) -> list[Fundamental]      # clauses with `rule`
def current_versions(keys: list[str]) -> dict[str, int | None]                # None = retired or not in effect
def update(identity, run_id, fundamental_id, *, text, rule, reason, password) -> Fundamental

# services/offers.py  (C)
def get(offer_id: str) -> Offer | None

# services/memory.py  (C)
def recall(identity, query: str, *, kinds: list[str], k: int = 3) -> list[Memory]
def remember(identity, run_id, *, kind, text, scope, ttl_days: int | None, source_type,
             auth_method: str = "jwt") -> Memory
def correct(identity, run_id, memory_id, new_text: str, *, auth_method: str = "jwt") -> Memory
def forget(identity, run_id, memory_id, reason: str, *, auth_method: str = "jwt") -> None

# services/campaigns.py  (C)
def submit(identity, run_id, *, name, text, ctx, facts, modality: str, file_id: str | None,
           compliance, campaign_id: str | None = None, source: str = "submitted",
           derived_from: int | None = None) -> Campaign     # campaign_id given → new version
def search(identity, query: str, *, k: int = 1) -> list[CampaignCard]   # role/team/status filtered
def get(identity, campaign_id) -> Campaign
def approve(identity, run_id, campaign_id, feedback: str | None) -> Campaign   # stores `approval`
def reject(identity, run_id, campaign_id, feedback: str) -> Campaign
def release(identity, run_id, campaign_id) -> Campaign      # raises StaleApproval(changes) if anything moved
class StaleApproval(Exception): ...   # router maps to 409; ad returns to pending_review

# services/media.py  (C)
def store(data: bytes, mime: str) -> str                         # returns GridFS file_id
def transcribe(file_id: str) -> str                              # audio in: ElevenLabs Scribe
def read_image(file_id: str) -> dict                             # image in: { text, visual_notes }, fast model
def synthesize_speech(text: str, language: str) -> str           # audio out: ElevenLabs TTS, stock voice → file_id
def render_image(copy: str, *, language: str, offer) -> str      # image out: brand template in code → PNG file_id
```

## 6. Shared shapes

```
Facts = { claims: [ { type: ClaimType, quote, values?: { rate_percent?, months?, amount?, fee? } } ],
          cta, tone, language }

ComplianceReport = {
  verdict: "pass" | "needs_changes" | "blocked",
  route: "none" | "auto_correct" | "draft_correction" | "human_review",
  route_reason: str,                               // the business rule that chose the route
  summary: str,                                    // <= 3 sentences, plain language: the verdict and why
  confidence: Confidence,                          // in the verdict as a whole; computed in code
  passed_checks: [ { check, detail } ],            // what was checked and found fine
  violations: [ { source: "fundamental" | "offer" | "memory",
                  basis: "code" | "model",         // code = deterministic check; model = judged
                  certainty?: "clear" | "likely" | "unclear",   // model findings: the judge's own label
                  reasoning: str,                  // <= 2 sentences: what the ad says, what is required, why they conflict
                  evidence: { policy_excerpt?, offer_field?, ad_value?, offer_value?, memory_text? },
                  confidence: Confidence,
                  fundamental_key?, version?,      // when source = fundamental or offer
                  memory_id?,                      // when source = memory
                  materiality: "material" | "disclosure" | "formatting",
                  quote, explanation, fix } ],
  corrected_copy: str | null,
  missing_inputs: [str],                           // e.g. ["offer_id"]; non-empty → run status needs_input
  checked_fundamentals: [ { key, version } ],
  offer_version: int | null,
  memories_used: [ memory_id ],
  cached: bool }

Route, in code:  any material violation, any offer mismatch, or missing_inputs → human_review, blocked
                 else any disclosure violation                                → draft_correction, needs_changes
                 else any formatting violation                                → auto_correct, needs_changes
                 else                                                         → none, pass
  then, stricter only:  any finding with certainty "unclear"                  → human_review
                        verdict pass and confidence band not "high"           → human_review (verdict stays pass)

cache_key = hash(ad text + offer id and version + consulted policy keys and versions + recalled memory ids)

Confidence = { score: 0..100, band: "high" | "medium" | "low", reasons: [str] }
             band: high >= 80, medium 50..79, low < 50
```

### Confidence scoring

Computed in code from the evidence. The model never supplies the number; it only labels each of its own findings `clear`, `likely` or `unclear`. The score measures how strong the evidence is. It is not a calibrated probability, and the weights below are starting values to tune.

```
input_quality    text 1.00 | audio transcript 0.90 | image reading 0.80 | image with hard-to-read fine print 0.60

Hallucination guard, before scoring:
    a model finding with a non-empty quote that does not appear in the ad text is dropped
    and counted in `passed_checks` as { check: "dropped_findings", detail: n }

Finding score
    basis "code" (budget cap, banned term, required line, offer mismatch)   start 100
    basis "model"                                                           start 55
        + 20   the cited clause is mandatory: tied to a claim type the ad makes, or with no claim
               type and so applying to every ad in scope; or it is a standing team instruction
        + 10   otherwise: the clause came from the per-claim similarity search
        + 10   the quote was verified word for word in the ad text
        + 10   certainty "clear"   |   0 "likely"   |   - 20 "unclear"
        +  5   a recalled past verdict on a similar ad agrees
        capped at 95
    then  x input_quality, rounded

Verdict score
    not a pass   the highest score among the findings that set the verdict
                 (material findings if blocked, else disclosure, else formatting)
    pass         100 x input_quality x coverage, minus 10 if any claim is typed "other"
                 coverage = claims with at least one applicable clause consulted / all claims
                            (1.0 when the ad makes no claims)

reasons          one plain sentence per component that applied, built in code, for example
                 "Quote found word for word in the ad", "Clause is mandatory for introductory-rate claims",
                 "Read from an image (input quality 0.80)", "1 of 4 claims had no applicable clause"
```

Confidence never loosens anything. It can send a result to human review; it cannot turn a finding into a pass or skip an approval.

```
Grounding = { band: "high" | "medium" | "low",       // UC5 answers
              sources: [ { type: "ad" | "offer", id, version, fields: [str] } ],
              note?: str }                           // e.g. "The ad does not state the annual fee"
            high   = every term stated comes from the offer record or the ad's stored facts
            medium = part of the answer comes from the ad's full text
            low    = the question could not be answered from the ad or the offer; say so

CampaignCard = { id, name, team, product, offer_id, region, channel, language, version, status,
                 modality: "text" | "audio" | "image", text,
                 asset: { type: "audio" | "image", url: "/assets/<file_id>" } | null,
                 summary, facts, source, derived_from?,
                 compliance_verdict, confidence_band, route, approved: bool, created_at }

RegenerateResult = { status: "regenerated" | "failed",
                     campaign: CampaignCard | null,     // the new version, when regenerated
                     report: ComplianceReport,          // passing report, or the remaining findings
                     attempts: 1 | 2 }

Card = { type: "compliance_report", data: ComplianceReport }
     | { type: "campaign", data: CampaignCard }
     | { type: "memory_change", data: { target: "fundamental" | "memory",
                                        id?, key?, kind?, scope?,
                                        before, after,
                                        status: "proposed" | "applied", version? } }
     | { type: "fundamentals_review", data: { gaps: [str], conflicts: [str], suggestions: [str] } }

MemoryChip = { id, kind, text }
```

## 7. HTTP API

All endpoints except `/auth/login` require `Authorization: Bearer <jwt>`. Errors: `401` bad or missing token or failed step-up, `403` denied by policy (a `deny` event is in the ledger), `404` not found or out of scope, `409` stale approval on release.

```
POST /auth/login           { email, password }                       → { token, user: Identity }
GET  /me                                                             → Identity

POST /chat                 { thread_id, run_id, message, file_id?, ad?: AdContext, use_memory: true }
                           → { reply, cards: [Card], memories_used: [MemoryChip],
                               run_id, intent, status, tokens: { in, out },
                               grounding?: Grounding }          // on UC5 answers
     AdContext = { name?, product, offer_id, region, channel, language?, budget?, campaign_id? }

POST /assets               multipart audio or image file              → { file_id, type: "audio" | "image" }
GET  /assets/{file_id}     ?token=<jwt>                               → the file, with its stored content type

POST /compliance/check     { text?, file_id?, campaign_id?, name?, product, offer_id, region, channel,
                             budget?, save: false, use_memory: true } → ComplianceReport

GET  /offers                                                          → [Offer]
GET  /offers/{id}                                                     → Offer

GET  /campaigns            ?status=&q=                                → [CampaignCard]
GET  /campaigns/{id}                                                  → Campaign (no embedding)
POST /campaigns/{id}/approve   { feedback? }                          → CampaignCard      (manager)
POST /campaigns/{id}/reject    { feedback }                           → CampaignCard      (manager)
POST /campaigns/{id}/regenerate                                       → RegenerateResult
POST /campaigns/{id}/release                                          → CampaignCard | 409 { changes: [str] }

GET  /fundamentals                                                    → [Fundamental (no embedding)]
GET  /fundamentals/{id}/history                                       → [FundamentalVersion]
PUT  /fundamentals/{id}    { text, rule?, reason, password }          → Fundamental       (manager, step-up)

GET  /memories             ?kind=&status=                             → [Memory (no embedding)]   (scoped to caller)
POST /memories             { kind, text, scope, ttl_days?, reason?, password? } → Memory
PATCH /memories/{id}       { text, reason?, password? }               → Memory (the new one)
DELETE /memories/{id}      { reason, password? }                      → 204

GET  /audit                ?run_id=&actor=&action=&limit=             → [LedgerEvent]
GET  /audit/stream         ?run_id=&token=<jwt>                       → text/event-stream of LedgerEvent
GET  /runs/{id}                                                       → Run
POST /runs/{id}/stop                                                  → Run
POST /runs/{id}/rollback                                              → Run               (manager)
```

Notes for the web app:
- The client generates `run_id` (uuid) before `POST /chat`, opens `/audit/stream?run_id=…` at the same time, and can call `/runs/{id}/stop` while the chat request is in flight.
- **Ad context comes from the form.** Product, offer, region, channel and budget are picked by the user and sent as `ad`; the model does not guess them.
- **UC4 is a two-step write.** `/chat` returns a `memory_change` card with `status: "proposed"`. The web app collects the password and reason and calls `PUT /fundamentals/{id}` or the `/memories` endpoints directly. The password never goes through `/chat` or the model.
- `password` on memory endpoints is required when the change is team-scoped.
- To review an audio or image ad: `POST /assets`, then send the returned `file_id` with the chat message or to `/compliance/check`.
- **Regenerate compliant version** on a report that is not a pass calls `POST /campaigns/{id}/regenerate` (or the user asks in chat). On `regenerated`, show the new version's card; on `failed`, show the remaining findings.
- **Report layout.** Top: verdict, overall confidence (score, band, reasons), `summary`, route with `route_reason`. Then each finding: the quote, the fix, its confidence, and on expand the `reasoning` and `evidence`. Then `passed_checks`. Label the score "evidence strength", not "probability".
- Show an ad by its `modality`: an `<img>` for images, an `<audio>` player for audio, the `text` otherwise. Always show `text` as well, since it is what was reviewed.
- `<audio>`, `<img>` and `EventSource` cannot send headers, so `/assets/{file_id}` and `/audit/stream` accept the JWT as a `token` query parameter.
