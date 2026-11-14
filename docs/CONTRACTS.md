# Contracts

Frozen interfaces between streams. Change this file only in a tiny dedicated PR announced in team chat.

Database: `greenlight` on the shared Atlas Sandbox cluster. Ids are ObjectIds unless stated; over the API they are strings. Timestamps are UTC datetimes.

Scope: UC1 review existing creative, UC4 memory updates, UC5 questions about an ad. See [FLOWS.md](FLOWS.md).

## 1. Identity

```
Identity = { user_id: str, email: str, name: str, role: "manager" | "marketer" | "sales", team: "national" | "quebec" }
```
Built from the JWT by `core/security.py::current_identity`. Never taken from a request body or model output.

## 2. Regions

Ads carry `region: "CA" | "CA-QC"`. Rules carry `region: "global" | "CA" | "CA-QC"`.

```python
def regions_for(ad_region: str) -> list[str]
#   "CA"    → ["global", "CA"]
#   "CA-QC" → ["global", "CA", "CA-QC"]
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
| `campaign.search` | yes | yes | yes (approved only) |
| `campaign.ask` | yes | yes | yes (approved only) |
| `campaign.approve` | yes | | |
| `fundamentals.read` | yes | yes | |
| `fundamentals.update` | yes + step-up | | |
| `fundamentals.review` | yes | | |
| `memory.read` | yes | yes | |
| `memory.write` | yes (team scope needs step-up) | self scope only | |
| `memory.forget` | yes + step-up | own notes only | |
| `run.stop` | yes | own runs | |
| `run.rollback` | yes | | |
| `audit.read` | yes | own runs | |

"Approved only", "self scope" and "own runs" are enforced by query filters in the owning service, in addition to the action check in the gate.

### `fundamentals` — company rules (semantic memory)
```
{ _id, key (unique, e.g. "regional.ca.origin_claims"),
  category: "brand" | "company_policy" | "budget" | "regional" | "consent" | "legal",
  region: "global" | "CA" | "CA-QC",
  title, text, summary (<= 60 words),
  rule?: { type: "budget_cap", team, max, currency: "CAD" }
       | { type: "banned_terms", terms: [str] }
       | { type: "required_line", region, channel, line },
  version: int, embedding: [float x 1024],
  updated_by: user_id, updated_at }
```

Seed set. This is fictional company policy for Solstice Coffee Co., loosely modelled on Canadian advertising practice. It is illustrative and not legal advice.

| key | category | region | hard rule | In one line |
|---|---|---|---|---|
| `brand.voice_tone` | brand | global | | Warm, plain, unhurried; no hype |
| `brand.naming_and_tagline` | brand | global | | How the brand name and taglines are written |
| `policy.claims_substantiation` | company_policy | global | | No "best", "number one" or similar without evidence on file |
| `policy.competitor_mentions` | company_policy | global | `banned_terms` | Do not name competitors |
| `budget.cap.national` | budget | global | `budget_cap` | Per-campaign cap for the national team, in CAD |
| `budget.cap.quebec` | budget | global | `budget_cap` | Per-campaign cap for the Quebec team, in CAD |
| `regional.ca.origin_claims` | regional | CA | | Do not say "Product of Canada" or "Made in Canada"; say "Roasted in Canada from imported beans" |
| `regional.ca.all_in_pricing` | regional | CA | | Advertised prices include all mandatory fees |
| `regional.ca.contests` | regional | CA | | Contest ads state "No purchase necessary" and point to the rules |
| `regional.ca.email_consent` | regional | CA | `required_line` | Email ads go only to consenting recipients and carry an unsubscribe line |
| `regional.qc.french_language` | regional | CA-QC | | Quebec ads are in French, or French is clearly predominant |
| `regional.qc.children_under_13` | regional | CA-QC | | No advertising directed at children under 13 in Quebec |
| `consent.voice_and_likeness` | consent | global | | No real person's name, voice or likeness without written consent on file |
| `consent.customer_testimonials` | consent | global | | Testimonials are genuine, current and used with permission |
| `legal.health_claims` | legal | global | | No health benefit claims for coffee |
| `legal.environmental_claims` | legal | CA | | No "green", "carbon neutral" or similar without evidence on file |

### `fundamentals_versions`
```
{ _id, fundamental_id, key, version, snapshot: <full previous document without embedding>,
  replaced_by: user_id, replaced_at, reason }
```

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
  result?: { status: "ok" | "blocked" | "error", summary, ref?: { collection, id } },
  undo?: { type: "fundamental.restore" | "memory.revert" | "campaign.rollback", ref },
  auth: { method: "jwt" | "jwt+password" },
  tokens?: { in, out } }
```
Validator (`$jsonSchema`): `ts`, `run_id`, `actor.user_id`, `actor.role`, `event`, `action`, `auth.method` are required; `event` and `decision` are enums. Code only ever inserts into this collection.

### `runs`
```
{ _id: run_id (uuid string, generated by the client), thread_id, actor, input,
  intent: "review" | "memory_update" | "ask",
  status: "running" | "completed" | "blocked" | "denied" | "stop_requested" | "stopped" | "rolled_back" | "error",
  memory_enabled: bool, memories_used: [memory_id], tokens: { in, out },
  started_at, ended_at }
```

### `campaigns` — the ad library
```
{ _id, team, name, region: "CA" | "CA-QC", channel: "radio" | "podcast" | "social" | "email",
  language: "en" | "fr", budget: { amount, currency: "CAD" },
  text (ad copy, or the transcript of an audio ad),
  summary (<= 60 words), description (what a listener or viewer would remember),
  facts: { cta, offer, claims: [str], tone, language },
  assets: [ { type: "audio", file_id, mime: "audio/mpeg" } ],
  source: "seed" | "submitted",
  status: "pending_review" | "approved" | "rejected" | "rolled_back",
  compliance: { verdict, violations: [...], checked_at, cache_key },
  embedding: [float x 1024],   // of description + summary
  created_by, approved_by?, review_feedback?, run_id, created_at }
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

### Others
- `checkpoints`, `checkpoint_writes` — LangGraph `MongoDBSaver`.
- `fs.files`, `fs.chunks` — GridFS audio.

## 4. Indexes

Vector indexes (type `vectorSearch`, cosine, 1024 dimensions, path `embedding`):

| Index | Collection | Filter fields |
|---|---|---|
| `fundamentals_vec` | `fundamentals` | `category`, `region` |
| `campaigns_vec` | `campaigns` | `status`, `team` |
| `memories_vec` | `memories` | `kind`, `status`, `scope.team`, `visibility_roles` |

```json
{ "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
    { "type": "filter", "path": "status" },
    { "type": "filter", "path": "team" }
] }
```

Regular indexes: `users.email` unique; `fundamentals.key` unique; `ledger {run_id: 1, ts: 1}`; `ledger {"actor.user_id": 1, ts: -1}`; `memories.expires_at` TTL with `expireAfterSeconds: 0`; `campaigns {team: 1, status: 1, created_at: -1}`.

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
def embed_query(text: str) -> list[float]

# core/llm.py  (B)
def main_model()   # compliance verdict only
def fast_model()   # router, Q&A, extraction, drafting

# services/compliance.py  (B)
def check(text: str, ctx: dict, identity, run_id: str, *, use_memory: bool = True) -> ComplianceReport
#   ctx = { region, channel, language?, budget?: {amount, currency}, campaign_id? }

# services/memory.py  (C)
def recall(identity, query: str, *, kinds: list[str], k: int = 3) -> list[Memory]
def remember(identity, run_id, *, kind, text, scope, ttl_days: int | None, source_type,
             auth_method: str = "jwt") -> Memory
def correct(identity, run_id, memory_id, new_text: str, *, auth_method: str = "jwt") -> Memory
def forget(identity, run_id, memory_id, reason: str, *, auth_method: str = "jwt") -> None

# services/campaigns.py  (C)
def submit(identity, run_id, *, name, text, ctx, file_id: str | None, compliance) -> Campaign
def search(identity, query: str, *, k: int = 1) -> list[CampaignCard]   # role/team/status filtered
def get(identity, campaign_id) -> Campaign
def set_status(identity, run_id, campaign_id, status, feedback: str | None) -> Campaign

# services/audio.py  (C)
def store_audio(data: bytes, mime: str) -> str      # returns GridFS file_id
def transcribe(file_id: str) -> str                 # ElevenLabs Scribe

# services/fundamentals.py  (A)
def list_all(identity) -> list[Fundamental]
def retrieve(query_vector, *, regions: list[str], k: int = 5) -> list[FundamentalSummary]   # used by compliance
def hard_rules(regions: list[str]) -> list[Fundamental]                                      # docs with `rule`
def update(identity, run_id, fundamental_id, *, text, rule, reason, password) -> Fundamental
```

## 6. Shared shapes

```
ComplianceReport = {
  verdict: "pass" | "needs_changes" | "blocked",
  violations: [ { source: "fundamental" | "memory",
                  fundamental_key?, version?,      // when source = fundamental
                  memory_id?,                      // when source = memory
                  severity: "low" | "medium" | "high",
                  quote, explanation, fix } ],
  checked_fundamentals: [ { key, version } ],
  memories_used: [ memory_id ],
  cached: bool }

cache_key = hash(ad text + consulted rule keys and versions + recalled memory ids)

CampaignCard = { id, name, team, region, channel, language, status, summary, facts,
                 audio_url: "/assets/<file_id>" | null, compliance_verdict, created_at }

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

All endpoints except `/auth/login` require `Authorization: Bearer <jwt>`. Errors: `401` bad or missing token or failed step-up, `403` denied by policy (a `deny` event is in the ledger), `404` not found or out of scope.

```
POST /auth/login           { email, password }                       → { token, user: Identity }
GET  /me                                                             → Identity

POST /chat                 { thread_id, run_id, message, file_id?, use_memory: true }
                           → { reply, cards: [Card], memories_used: [MemoryChip],
                               run_id, intent, status, tokens: { in, out } }

POST /assets               multipart audio file                       → { file_id }
GET  /assets/{file_id}     ?token=<jwt>                               → audio/mpeg stream

POST /compliance/check     { text?, file_id?, campaign_id?, name?, region, channel, budget?,
                             save: false, use_memory: true }          → ComplianceReport

GET  /campaigns            ?status=&q=                                → [CampaignCard]
GET  /campaigns/{id}                                                  → Campaign (no embedding)
POST /campaigns/{id}/approve   { feedback? }                          → CampaignCard      (manager)
POST /campaigns/{id}/reject    { feedback }                           → CampaignCard      (manager)

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
- **UC4 is a two-step write.** `/chat` returns a `memory_change` card with `status: "proposed"`. The web app collects the password and reason and calls `PUT /fundamentals/{id}` or the `/memories` endpoints directly. The password never goes through `/chat` or the model.
- `password` on memory endpoints is required when the change is team-scoped.
- To review an audio ad: `POST /assets`, then send the returned `file_id` with the chat message or to `/compliance/check`.
- `<audio>` and `EventSource` cannot send headers, so those two endpoints accept the JWT as a `token` query parameter.
