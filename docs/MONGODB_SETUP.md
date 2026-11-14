# MongoDB setup: collections, schema, indexes, example data

> **Current data set: NorthPlay.** The database is built from `northplay-demo-data/` in two steps:
> `python -m scripts.build_seed` turns that folder into `backend/seed/*.json`, and
> `python -m scripts.load_db --db greenlight --shared --password <SEED_PASSWORD>` creates the collections,
> validators and indexes below and loads the seed. It holds 7 users, 15 policy clauses, 15 past ads with
> their images, 60 memories (Slack decisions, deck slides, past decisions) and the raw Slack, deck, regulation
> and ad-decision records they came from. The "Example data" section at the end of this page still describes
> the earlier fictional-bank fixtures, which the offline tests use; the validators and indexes are current.

What to create in the shared Atlas cluster, in what order, and the data that has to be in it before anyone can build or demo. Field-by-field shapes are in [CONTRACTS.md](CONTRACTS.md); this file is the execution plan.

Database: **`greenlight`** on the hackathon sandbox `Cluster0`.

## At a glance

| # | Collection | Holds | Validation | Seeded | Source file |
|---|---|---|---|---|---|
| 1 | `policies` | What each role may do | strict | 3 | `backend/seed/policies.json` |
| 2 | `users` | Who can sign in, with role and team | strict | 6 | `backend/seed/users.json` |
| 3 | `offers` | Approved promotion terms | strict | 2 | `backend/seed/offers.json` |
| 4 | `fundamentals` | Policy clauses, with embeddings | strict | 18 (17 approved, 1 retired) | `backend/seed/fundamentals.json` |
| 5 | `fundamentals_versions` | Earlier versions of clauses | strict | 3 | derived from `previous_texts` |
| 6 | `campaigns` | The ad library: text, audio and image ads, with embeddings | warn | 9 | `backend/seed/campaigns.json` |
| 7 | `memories` | Team instructions, facts and past verdicts, with embeddings | strict | 9 | `backend/seed/memories.json` |
| 8 | `ledger` | Audit events | strict | one pair per seeded approval and release | written by the seed script |
| 9 | `runs` | One document per request | warn | 0 | |
| 10 | `fs.files`, `fs.chunks` | Audio and image files (GridFS) | none | 4 files | produced by the seed script |
| 11 | `checkpoints`, `checkpoint_writes` | Conversation state | none | 0 | created by LangGraph on first use |

"Strict" rejects a document that breaks the schema. "Warn" logs it and lets it through; `campaigns` and `runs` change shape fastest during the build, so they warn until the feature freeze and can be switched to strict then.

## Steps

| Step | What | Who | Time |
|---|---|---|---|
| 1 | Database user and network access | Repo owner | 5 min |
| 2 | Create the nine collections with validators | Stream 0 (`setup_db.py`), finished by A2 | 10 min |
| 3 | Create regular and TTL indexes | Stream 0 (`setup_db.py`) | 2 min |
| 4 | Create the three vector search indexes and wait for READY | Stream 0 (`setup_db.py`) | 3 min + about 1 min to build |
| 5 | Load reference data: `policies`, `users`, `offers`, `fundamentals` | Stream 0 (`seed.py`) | 5 min |
| 6 | Load demo data: media files, `campaigns`, `memories`, seeded ledger events | Stream C, task C1 (`seed.py`) | 20 min |
| 7 | Run the verification queries | Whoever ran step 6 | 3 min |

Both scripts must be safe to run again. `setup_db.py` creates what is missing and updates validators in place. `seed.py` upserts on the natural key (`_id`, `email`, `key`, `ref`) and never deletes anything it did not create.

### Step 1 — Database user and network access

- Create database user `greenlight_app` with **`readWrite` and `dbAdmin` on `greenlight` only**. `readWrite` covers data, index and search-index creation; `dbAdmin` is needed to change a validator on an existing collection (`collMod`).
- Add each teammate's IP to the access list.
- Share the connection string privately. See [SETUP.md](SETUP.md).

### Step 2 — Collections and validators

Create each collection with its validator. If it already exists, apply the validator with `collMod`.

```python
def ensure(db, name, schema, action="error"):
    opts = {"validator": {"$jsonSchema": schema}, "validationLevel": "strict", "validationAction": action}
    if name in db.list_collection_names():
        db.command("collMod", name, **opts)
    else:
        db.create_collection(name, **opts)
```

Dates must be stored as BSON dates, not strings. The TTL index and the effective-date filters do not work on strings. The seed files hold ISO strings; `seed.py` converts them.

**`policies`** (strict)
```json
{ "bsonType": "object", "required": ["_id", "actions"],
  "properties": {
    "_id": { "enum": ["manager", "marketer", "sales"] },
    "actions": { "bsonType": "array", "items": { "enum": [
      "compliance.check", "campaign.submit", "asset.regenerate", "campaign.approve", "campaign.release",
      "campaign.search", "campaign.ask", "fundamentals.read", "fundamentals.update", "fundamentals.review",
      "memory.read", "memory.write", "memory.forget", "run.stop", "run.rollback", "audit.read" ] } },
    "updated_at": { "bsonType": "date" } } }
```

**`users`** (strict)
```json
{ "bsonType": "object", "required": ["email", "name", "role", "team", "password_hash", "created_at"],
  "properties": {
    "email": { "bsonType": "string" },
    "name": { "bsonType": "string" },
    "role": { "enum": ["manager", "marketer", "sales"] },
    "team": { "bsonType": "string" },
    "password_hash": { "bsonType": "string" },
    "created_at": { "bsonType": "date" } } }
```

**`offers`** (strict)
```json
{ "bsonType": "object",
  "required": ["_id", "product", "card_name", "teams", "standard_rate_percent", "annual_fee", "valid_from", "valid_to", "version"],
  "properties": {
    "_id": { "bsonType": "string" },
    "product": { "bsonType": "string" },
    "card_name": { "bsonType": "string" },
    "teams": { "bsonType": "array", "items": { "bsonType": "string" } },
    "intro_rate": { "bsonType": ["object", "null"], "required": ["rate_percent", "months"],
      "properties": { "rate_percent": { "bsonType": ["int", "double"] }, "months": { "bsonType": "int" } } },
    "standard_rate_percent": { "bsonType": ["int", "double"] },
    "bonus": { "bsonType": ["object", "null"] },
    "annual_fee": { "bsonType": ["int", "double"] },
    "valid_from": { "bsonType": "date" }, "valid_to": { "bsonType": "date" },
    "version": { "bsonType": "int" } } }
```

**`fundamentals`** (strict)
```json
{ "bsonType": "object",
  "required": ["key", "category", "region", "product", "title", "text", "summary", "claim_types",
               "materiality", "status", "effective_from", "version", "updated_at"],
  "properties": {
    "key": { "bsonType": "string" },
    "category": { "bsonType": "string" },
    "region": { "bsonType": "string" },
    "product": { "bsonType": "string" },
    "title": { "bsonType": "string" }, "text": { "bsonType": "string" }, "summary": { "bsonType": "string" },
    "source_section": { "bsonType": "string" },
    "claim_types": { "bsonType": "array", "items": { "bsonType": "string" } },
    "materiality": { "enum": ["material", "disclosure", "formatting"] },
    "approved_fix": { "bsonType": "object" },
    "rule": { "bsonType": "object", "required": ["type"],
      "properties": { "type": { "enum": ["budget_cap", "banned_terms", "required_line", "required_elements", "offer_match"] } } },
    "status": { "enum": ["approved", "draft", "retired"] },
    "effective_from": { "bsonType": "date" },
    "effective_to": { "bsonType": ["date", "null"] },
    "version": { "bsonType": "int", "minimum": 1 },
    "embedding": { "bsonType": "array" },
    "updated_at": { "bsonType": "date" } } }
```

**`fundamentals_versions`** (strict)
```json
{ "bsonType": "object",
  "required": ["fundamental_id", "key", "version", "snapshot", "replaced_at", "reason"],
  "properties": {
    "key": { "bsonType": "string" },
    "version": { "bsonType": "int", "minimum": 1 },
    "snapshot": { "bsonType": "object" },
    "replaced_at": { "bsonType": "date" },
    "reason": { "bsonType": "string" } } }
```

**`campaigns`** (warn)
```json
{ "bsonType": "object",
  "required": ["team", "name", "product", "region", "channel", "language", "modality",
               "version", "text", "status", "created_by", "created_at"],
  "properties": {
    "team": { "bsonType": "string" },
    "product": { "bsonType": "string" },
    "offer_id": { "bsonType": ["string", "null"] },
    "region": { "bsonType": "string" },
    "channel": { "bsonType": "string" },
    "language": { "enum": ["en", "fr"] },
    "modality": { "enum": ["text", "audio", "image"] },
    "version": { "bsonType": "int", "minimum": 1 },
    "text": { "bsonType": "string" },
    "assets": { "bsonType": "array", "items": { "bsonType": "object", "required": ["type", "file_id", "mime"],
      "properties": { "type": { "enum": ["audio", "image"] } } } },
    "source": { "enum": ["seed", "submitted", "regenerated"] },
    "status": { "enum": ["pending_review", "approved", "released", "rejected", "rolled_back"] },
    "embedding": { "bsonType": "array" },
    "created_at": { "bsonType": "date" } } }
```

**`memories`** (strict)
```json
{ "bsonType": "object",
  "required": ["kind", "text", "scope", "visibility_roles", "status", "source", "created_by", "created_at"],
  "properties": {
    "kind": { "enum": ["semantic", "episodic", "procedural"] },
    "text": { "bsonType": "string" },
    "scope": { "bsonType": "object", "required": ["team"],
      "properties": { "team": { "bsonType": "string" }, "user_id": { "bsonType": ["string", "null"] } } },
    "visibility_roles": { "bsonType": "array", "minItems": 1, "items": { "enum": ["manager", "marketer", "sales"] } },
    "status": { "enum": ["active", "superseded", "forgotten"] },
    "expires_at": { "bsonType": ["date", "null"] },
    "source": { "bsonType": "object", "required": ["type"],
      "properties": { "type": { "enum": ["agent", "manager_instruction", "review_feedback", "user_note", "slack", "strategy_deck", "ad_decision"] } } },
    "embedding": { "bsonType": "array" },
    "created_at": { "bsonType": "date" } } }
```

**`ledger`** (strict)
```json
{ "bsonType": "object",
  "required": ["ts", "run_id", "actor", "event", "action", "auth"],
  "properties": {
    "ts": { "bsonType": "date" },
    "run_id": { "bsonType": "string" },
    "actor": { "bsonType": "object", "required": ["user_id", "role"],
      "properties": { "user_id": { "bsonType": "string" },
                      "role": { "enum": ["manager", "marketer", "sales"] },
                      "team": { "bsonType": "string" } } },
    "event": { "enum": ["decision", "outcome", "stop", "rollback"] },
    "action": { "bsonType": "string" },
    "decision": { "enum": ["allow", "deny"] },
    "auth": { "bsonType": "object", "required": ["method"],
      "properties": { "method": { "enum": ["jwt", "jwt+password"] } } } } }
```

**`runs`** (warn)
```json
{ "bsonType": "object", "required": ["_id", "actor", "status", "started_at"],
  "properties": {
    "_id": { "bsonType": "string" },
    "intent": { "enum": ["review", "regenerate", "memory_update", "ask", "approve", "release"] },
    "status": { "enum": ["running", "completed", "blocked", "needs_input", "denied",
                         "stop_requested", "stopped", "rolled_back", "error"] },
    "started_at": { "bsonType": "date" } } }
```

### Step 3 — Regular and TTL indexes

| Collection | Index | Options | Why |
|---|---|---|---|
| `users` | `{ email: 1 }` | unique | Login |
| `fundamentals` | `{ key: 1 }` | unique | Lookup by key; version checks at release |
| `fundamentals` | `{ claim_types: 1, status: 1 }` | | Mandatory clauses for a claim type |
| `fundamentals_versions` | `{ key: 1, version: -1 }` | | History |
| `campaigns` | `{ team: 1, status: 1, created_at: -1 }` | | Library listing |
| `campaigns` | `{ ref: 1 }` | unique, sparse | Seed upserts |
| `memories` | `{ expires_at: 1 }` | `expireAfterSeconds: 0` | Expiry (TTL) |
| `memories` | `{ "scope.team": 1, status: 1, kind: 1 }` | | Memory page listing |
| `ledger` | `{ run_id: 1, ts: 1 }` | | Reconstruct a run |
| `ledger` | `{ "actor.user_id": 1, ts: -1 }` | | Audit by person |
| `runs` | `{ "actor.user_id": 1, started_at: -1 }` | | A user's own runs |

The TTL monitor runs about once a minute, so recall also filters on `expires_at` in the query.

### Step 4 — Vector search indexes

All three: type `vectorSearch`, field `embedding`, 1024 dimensions (Voyage `voyage-3.5`), cosine.

**`fundamentals_vec`** on `fundamentals`
```json
{ "fields": [
  { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
  { "type": "filter", "path": "category" },
  { "type": "filter", "path": "region" },
  { "type": "filter", "path": "product" },
  { "type": "filter", "path": "status" } ] }
```

**`campaigns_vec`** on `campaigns`
```json
{ "fields": [
  { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
  { "type": "filter", "path": "status" },
  { "type": "filter", "path": "team" } ] }
```

**`memories_vec`** on `memories`
```json
{ "fields": [
  { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
  { "type": "filter", "path": "kind" },
  { "type": "filter", "path": "status" },
  { "type": "filter", "path": "scope.team" },
  { "type": "filter", "path": "visibility_roles" } ] }
```

```python
from pymongo.operations import SearchIndexModel
db.fundamentals.create_search_index(SearchIndexModel(name="fundamentals_vec", type="vectorSearch", definition=DEFINITION))
```

Skip creation when `list_search_indexes()` already shows the name. Poll until `queryable` is true before seeding checks run.

What is embedded: `fundamentals` → `title` + `text`; `campaigns` → `description` + `summary`; `memories` → `text`. Documents use `input_type="document"`; searches use `input_type="query"`.

### Step 5 — Reference data

Load in this order, because later documents refer to earlier ones.

1. **`policies`** — insert the three documents as they are.
2. **`users`** — for each entry add `password_hash` (bcrypt of `SEED_PASSWORD`) and `created_at`.
3. **`offers`** — convert `valid_from` and `valid_to` to dates.
4. **`fundamentals`** — for each entry: convert the dates, embed `title` + `text`, set `updated_by` to the national manager and `updated_at` to now. Remove `previous_texts` before inserting.
5. **`fundamentals_versions`** — for each entry of `previous_texts`, insert one snapshot (version 1, 2, …) with `reason: "seed"`. This gives `credit.approval_claims` one earlier version and `credit.intro_rate_disclosure` two.

### Step 6 — Demo data

1. **Media files into GridFS.** Nothing binary is committed to the repo.
   - Audio ads (`nat-radio-slow-mornings`, `qc-radio-remises`): send `text` to ElevenLabs text-to-speech, store the mp3.
   - Image ads (`nat-banner-fall-cashback`, `qc-banner-remises`): render `text` on the brand template, store the PNG.
   - Until `services/media.py` exists, seed these four ads without `assets` and re-run the seed after task C4/C5.
2. **`campaigns`** — for each entry: resolve `created_by` / `approved_by` / `rejected_by` emails to user ids; set `version: 1`, `source: "seed"`, `created_at`; attach `assets`; embed `description` + `summary`. For `approved` and `released` ads, build `approval` from the current versions of the clauses that apply to the ad and the offer's version. For `released` ads set `released_at`.
3. **`memories`** — for each entry: build `scope` from `team` and `user_email`; set `status: "active"`; set `expires_at` from `ttl_days` or `ttl_minutes` (null when neither is set); set `source: { type, run_id: "seed" }`; embed `text`.
4. **`ledger`** — for every seeded approval and release, insert a `decision` and an `outcome` event with the approving manager as actor, `run_id: "seed-<ref>"` and `params.seeded: true`. A seeded approval with no audit trail would be the one gap in the ledger.

### Step 7 — Verification

| Check | Expected |
|---|---|
| Document counts | `policies` 3, `users` 6, `offers` 2, `fundamentals` 18, `fundamentals_versions` 3, `campaigns` 9, `memories` 9 |
| Search indexes | `fundamentals_vec`, `campaigns_vec`, `memories_vec` all queryable |
| Every `fundamentals`, `campaigns`, `memories` document has an `embedding` of length 1024 | 0 without |
| Insert `{ "event": "decision" }` into `ledger` | Rejected by the validator |
| Insert a memory with `kind: "rumour"` | Rejected by the validator |
| Vector search on `fundamentals` for "guaranteed approval", filter `status: approved`, `region` in `global`, `CA`, `product` in `credit_card`, `all` | `credit.approval_claims` is the top result; the retired holiday clause never appears |
| Vector search on `campaigns` for "email about 300 dollars cash back", filter `team: national`, `status: released` | `nat-email-fall-cashback` or `nat-banner-fall-cashback`; never a pending or Quebec ad |
| Vector search on `memories` for "credit approval wording", filter `scope.team: quebec` | No national memories returned |
| Five minutes after seeding | `nat-epi-rewards-hold` is gone |

## Example data

The full data is in `backend/seed/`. What it contains and why each piece is there:

### Users (6)

Three roles in each of two teams, so that role limits and team isolation can both be shown.

| Email | Role | Team |
|---|---|---|
| `manager.national@tamarack.test` | manager | national |
| `marketer.national@tamarack.test` | marketer | national |
| `sales.national@tamarack.test` | sales | national |
| `manager.quebec@tamarack.test` | manager | quebec |
| `marketer.quebec@tamarack.test` | marketer | quebec |
| `sales.quebec@tamarack.test` | sales | quebec |

### Offers (2)

| Offer | Card | Intro rate | Standard rate | Bonus | Annual fee | Used for |
|---|---|---|---|---|---|---|
| `TCB-FALL-2026` | Tamarack Cashback Card | 0% on purchases for 10 months | 20.99% | $300 after $1,500 in 90 days | $0 | The running example and most ads |
| `TRC-WINTER-2026` | Tamarack Rewards Card | none | 19.99% | $150 after $1,000 in 60 days | $99 | Annual-fee and "no intro rate" cases |

### Policy clauses (18)

Seventeen approved clauses and one retired clause that exists to prove retired clauses are never retrieved.

| Key | Version | Applies to | Kind of finding | Checked in code |
|---|---|---|---|---|
| `brand.voice_tone` | 1 | all ads | formatting | |
| `brand.naming_and_logo` | 1 | all ads | formatting | |
| `brand.required_footer` | 1 | card ads | disclosure | required line |
| `policy.offer_accuracy` | 1 | all ads | material | offer match |
| `policy.claims_substantiation` | 1 | all ads | material | |
| `policy.competitor_mentions` | 1 | all ads | material | banned terms |
| `budget.cap.national` | 1 | national team | material | budget cap, CAD 25,000 |
| `budget.cap.quebec` | 1 | Quebec team | material | budget cap, CAD 15,000 |
| `credit.approval_claims` | 2 | card ads in Canada | material | |
| `credit.intro_rate_disclosure` | 3 | card ads in Canada | disclosure | |
| `credit.bonus_conditions` | 1 | card ads in Canada | disclosure | |
| `credit.annual_fee_disclosure` | 1 | card ads in Canada | disclosure | |
| `credit.responsible_borrowing` | 1 | card ads in Canada | material | |
| `regional.ca.email_consent` | 1 | email in Canada | disclosure | required line |
| `regional.qc.french_language` | 1 | Quebec ads | material | |
| `regional.qc.credit_terms` | 1 | card ads in Quebec | disclosure | |
| `consent.testimonials_and_likeness` | 1 | all ads | material | |
| `brand.holiday_tagline_2025` | 1 | retired | formatting | |

One clause as stored:

```json
{
  "key": "credit.approval_claims",
  "category": "legal", "region": "CA", "product": "credit_card",
  "title": "Approval claims",
  "text": "Do not promise or imply that an applicant will be approved. Phrases such as 'guaranteed approval', 'instant approval', 'pre-approved' and 'everyone qualifies' are not permitted, because every application is subject to a credit check. Where an ad refers to applying, the approved wording is 'Subject to credit approval'.",
  "summary": "Never promise or imply approval. The approved wording is 'Subject to credit approval'.",
  "source_section": "Card Marketing Standard, section 3.1",
  "claim_types": ["approval"], "materiality": "material",
  "approved_fix": { "en": "Subject to credit approval.", "fr": "Sous réserve de l'approbation du crédit." },
  "status": "approved",
  "effective_from": { "$date": "2026-03-01T00:00:00Z" }, "effective_to": null,
  "version": 2,
  "embedding": [0.0213, -0.0458, "... 1,024 numbers"],
  "updated_by": "<user id>", "updated_at": { "$date": "2026-11-14T17:00:00Z" }
}
```

### Ads (9)

All three forms, both teams, both languages, and every status the demo needs.

| Ref | Team | Form | Language | Offer | Status | Why it is there |
|---|---|---|---|---|---|---|
| `nat-email-fall-cashback` | national | text | en | TCB-FALL | released | What sales finds for "an email about $300 cash back" |
| `nat-banner-fall-cashback` | national | image | en | TCB-FALL | released | Sales pulls a banner; image retrieval |
| `nat-radio-slow-mornings` | national | audio | en | TCB-FALL | approved | Release is refused after a policy edit |
| `nat-email-best-card` | national | text | en | TCB-FALL | pending, blocked | Superlative, "free money", missing bonus conditions |
| `nat-social-rewards-switch` | national | text | en | TRC-WINTER | rejected | Names a competitor, misstates the annual fee |
| `qc-radio-remises` | quebec | audio | fr | TCB-FALL | released | French audio; Quebec sales retrieval |
| `qc-email-remises` | quebec | text | fr | TCB-FALL | pending, passes | Passes today; flagged after the manager's new instruction |
| `qc-banner-remises` | quebec | image | fr | TCB-FALL | approved | French image ad |
| `qc-email-english-only` | quebec | text | en | TCB-FALL | pending, blocked | English-only ad aimed at Quebec |

The running example ("Guaranteed approval! …") is **not** seeded. It is submitted live.

One ad as stored (an image ad):

```json
{
  "ref": "nat-banner-fall-cashback",
  "team": "national", "name": "Fall cashback banner",
  "product": "credit_card", "offer_id": "TCB-FALL-2026",
  "region": "CA", "channel": "display", "language": "en",
  "modality": "image", "version": 1,
  "budget": { "amount": 8000, "currency": "CAD" },
  "text": "$300 cash back. After $1,500 in purchases in your first 3 months. 0% interest on purchases for 10 months, then 20.99%. Tamarack Cashback Card. Subject to credit approval. Conditions apply.",
  "visual_notes": "Dark green banner. Large headline '$300 cash back'. A picture of the card on the right. Fine print along the bottom edge, legible. No people shown.",
  "description": "A dark green web banner with '$300 cash back' in large type and a picture of the Tamarack Cashback Card.",
  "summary": "Display banner for the fall cashback offer: $300 cash back after $1,500 in purchases in the first 3 months, 0% on purchases for 10 months then 20.99%.",
  "facts": { "claims": [
      { "type": "rewards_bonus", "quote": "$300 cash back. After $1,500 in purchases in your first 3 months", "values": { "amount": 300 } },
      { "type": "intro_rate", "quote": "0% interest on purchases for 10 months, then 20.99%", "values": { "rate_percent": 0, "months": 10 } } ],
    "cta": null, "tone": "plain", "language": "en" },
  "assets": [ { "type": "image", "file_id": "<GridFS id>", "mime": "image/png" } ],
  "source": "seed", "status": "released",
  "compliance": { "verdict": "pass", "route": "none" },
  "approval": { "by": "<manager id>", "at": { "$date": "2026-11-14T17:05:00Z" }, "ad_version": 1,
                "policy_versions": [ { "key": "credit.intro_rate_disclosure", "version": 3 },
                                     { "key": "credit.bonus_conditions", "version": 1 },
                                     { "key": "policy.offer_accuracy", "version": 1 },
                                     { "key": "brand.required_footer", "version": 1 } ],
                "offer_version": 1, "run_id": "seed-nat-banner-fall-cashback" },
  "embedding": [0.0311, -0.0102, "... 1,024 numbers"],
  "created_by": "<marketer id>", "created_at": { "$date": "2026-11-14T17:00:00Z" },
  "released_at": { "$date": "2026-11-14T17:06:00Z" }
}
```

### Memories (9)

| Ref | Team | Kind | Lives | What it shows |
|---|---|---|---|---|
| `nat-proc-unsubscribe-last` | national | procedural | until corrected | A standing instruction that shapes corrected copy |
| `nat-sem-english-only` | national | semantic | until corrected | A team fact |
| `nat-epi-instant-approval` | national | episodic | 30 days | A past verdict that agrees with the running example |
| `nat-epi-rewards-hold` | national | episodic | 5 minutes | Expiry, live |
| `nat-note-short-copy` | national, one marketer | semantic | until corrected | A personal note only its author can recall |
| `qc-proc-remise-en-argent` | quebec | procedural | until corrected | A Quebec-only instruction; must never reach the national team |
| `qc-proc-banner-sizes` | quebec | procedural | until corrected | The one to forget in the demo |
| `qc-sem-french-first` | quebec | semantic | until corrected | A team fact |
| `qc-epi-fine-print` | quebec | episodic | 30 days | A past verdict on an image ad |

The instruction "Quebec card ads must include 'Sous réserve de l'approbation du crédit.'" is **not** seeded. The Quebec manager adds it live.

One memory as stored:

```json
{
  "kind": "episodic",
  "text": "A national email ad for TCB-FALL-2026 was blocked for saying 'instant approval'. The version saying 'Subject to credit approval' was approved.",
  "scope": { "team": "national", "user_id": null },
  "visibility_roles": ["manager", "marketer"],
  "status": "active",
  "expires_at": { "$date": "2026-12-14T17:00:00Z" },
  "source": { "type": "agent", "run_id": "seed" },
  "embedding": [0.0127, 0.0398, "... 1,024 numbers"],
  "created_by": "<marketer id>", "created_at": { "$date": "2026-11-14T17:00:00Z" },
  "use_count": 0, "last_used_at": null
}
```

### Ledger events

Empty apart from the seeded approvals and releases. One event as stored:

```json
{
  "ts": { "$date": "2026-11-14T17:05:00Z" },
  "run_id": "seed-nat-banner-fall-cashback", "thread_id": null,
  "actor": { "user_id": "<manager id>", "email": "manager.national@tamarack.test", "role": "manager", "team": "national" },
  "event": "decision", "action": "campaign.approve",
  "params": { "campaign_ref": "nat-banner-fall-cashback", "ad_version": 1, "seeded": true },
  "decision": "allow", "reason": "role manager holds campaign.approve",
  "policy_refs": [ { "key": "credit.intro_rate_disclosure", "version": 3 } ],
  "auth": { "method": "jwt" }
}
```

## Rules for the shared database

- Never drop a collection or an index. Never run an unfiltered delete or update.
- Change a validator or an index only by editing `setup_db.py` and re-running it.
- Reseeding upserts; it does not wipe. To start clean, use your own database: `MONGODB_DB=greenlight_<yourname>`.
- Do not change the embedding model or its dimensions after step 4.
