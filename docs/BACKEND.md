# The backend as built

Branch `agent/ai-flows`. Everything under `backend/` except the two data scripts. This page says what exists, how to run it, what has and has not been verified, and what the data and web app owners need to match.

## What is there

| Piece | File | State |
|---|---|---|
| Review engine (UC1) | `services/compliance.py`, `compliance_rules.py`, `confidence.py` | Built. Verified live on the seed files |
| Policy gate and ledger | `core/gate.py` | Built. Verified offline |
| Identity, tokens, step-up password | `core/security.py` | Built. Verified offline |
| Chat graph: route → lane | `agent/graph.py`, `agent/lanes.py` | Built. Verified offline with model calls canned |
| Regenerate a compliant version | `services/compliance.py`, `agent/lanes.py` | Built. Copy path verified live; filing verified offline |
| Policy clauses: versioned edit, restore | `services/fundamentals.py` | Built. Verified offline |
| Governed memory | `services/memory.py` | Built. Scoping and writes verified offline; vector recall not yet |
| Ad library: versions, approve, gated release | `services/campaigns.py` | Built. Verified offline; vector search not yet |
| Media in and out | `services/media.py` | Built. Speech, transcription, image reading and banner rendering verified live |
| Audit, live stream, stop, rollback | `routers/audit.py`, `routers/runs.py` | Built. Verified offline, except the live stream |
| API, 27 endpoints | `routers/*` | Built. Matches `CONTRACTS.md` section 7, with the differences listed below |

**Verified live on Atlas, against a scratch database.** The shared `greenlight` database does not exist yet, so `scripts/fake_data.py` built `greenlight_test` on the sandbox cluster from `docs/MONGODB_SETUP.md` and `backend/seed/`, and the whole backend was run against it:

| Check | Result |
|---|---|
| `scripts/smoke.py --audio` | 36 of 36: review, regenerate, approve, stale release, rollback, questions, memory changing a verdict, team isolation, audio in and out |
| Image in and out | A banner is read, reviewed with the same findings as its text version at lower confidence, and regenerated as a new banner |
| Atlas vector search | Clauses, memories and ads, each with its team, role, region and status filters; a retired clause is never returned |
| Live ledger stream | The allow decision reaches the stream while the review is still running; the stream closes when the run ends |
| Stop | Requested mid-review; the run halted before filing and nothing was saved |
| Conversation state | Stored in MongoDB; a follow-up "it" resolves to the ad just reviewed |
| Expiry and validators | The five-minute memory was removed by the TTL index; the validators from `MONGODB_SETUP.md` accepted every document the backend wrote and rejected malformed ones |

The image, stream, stop and conversation checks are saved as `scripts/smoke_extras.py`. That saved copy has one corrected expectation and has not itself been re-run.

Not checked: that two users' same-named threads stay separate (it follows from how thread ids are built, but no test exercises it), and how traces look in LangSmith.

**Not built:** reuse of a stored verdict for an unchanged ad (the key is stored, the lookup is not wired), the manager's "review our policies for gaps" request, a round-trip transcription check on regenerated audio, and turning reject feedback into a memory.

## How a chat turn runs

An explicit graph with two steps, not a free tool-calling agent:

1. **Route.** A file or pasted ad copy is a review, with no model call. Otherwise the fast model classifies the message as review, regenerate, memory update, ask, approve/release, or other.
2. **Act.** Code checks the role against `policies` for the action that intent needs. A role that lacks it gets a fixed refusal, a `deny` on the ledger, and no further model call. Otherwise the lane runs, each step a separate gated action.

No tool schema is ever sent to a model. The model is called for: routing, claim extraction, image reading, the verdict, one copy repair, drafting a memory change, and answering a question.

## How a review chooses clauses

1. Clauses that apply at all: right product, right region, approved, in effect today.
2. Clauses with a rule (budget cap, required line, offer match) are decided in code and not shown to the judge.
3. The judge is shown, at most twelve: clauses mandatory for a claim type the ad makes; then clauses with no claim type, which apply to every ad (language, tone, responsible borrowing); then other clauses the per-claim similarity search found.

General clauses are always included because a similarity search on an English credit card ad does not find "Quebec ads must be in French".

## Measured

| | |
|---|---|
| Live suite, 9 seeded ads | 9 of 9 match the expected verdict |
| Running example | Blocked, human review, the six expected clauses cited; its corrected copy passes on re-review |
| One review | About 10 s and 5,400 input tokens (1,900 extraction, 3,500 verdict) at `LLM_EFFORT=low` |
| Same review at `LLM_EFFORT=medium` | About 35 s, same findings |
| Speech, 30 words | 2 s to synthesize; transcript came back accurate |
| Image reading | 4 s; returned the banner's text exactly, fine print included |

## Things that will bite

- **Voyage rate limit.** A Voyage account without a payment method allows 3 requests a minute. A review makes 2 embedding requests (one for the ad and its claims, one for what it files), so the app waits and retries when limited. Adding a payment method in the Voyage dashboard lifts the limit; the free token allowance still applies.
- **LangSmith.** Set `LANGSMITH_PROJECT`, or the `LANGSMITH_AGENT_ID` / `LANGSMITH_AGENT_ENVIRONMENT` pair, never both. With both set LangSmith refuses to trace.
- **Python.** 3.12 or later. On macOS the system `python3` is 3.9; use `python3.13`.
- **Banner font.** Banners need a font with accented letters. Common system fonts are found automatically; otherwise set `BANNER_FONT` to a `.ttf` file. Without one, a French banner is refused, not rendered wrongly.

## For the data owner

`scripts/fake_data.py` is a working implementation of `MONGODB_SETUP.md` steps 2 to 6: it reads the validators and vector index definitions out of that document, loads `backend/seed/`, produces the seeded audio and banners, and upserts on natural keys. Use it as is, or as the reference for `setup_db.py` and `seed.py`:

```bash
python -m scripts.fake_data --db greenlight_test --password <test password>      # a scratch database
python -m scripts.fake_data --db greenlight --shared --password <SEED_PASSWORD>  # the shared one
```

The backend reads the collections exactly as `CONTRACTS.md` and `MONGODB_SETUP.md` describe them. These details matter:

| Topic | The backend expects |
|---|---|
| Embedded text for a clause | `fundamentals.clause_document(clause)`, which is `"{title}. {text}"` |
| Embedded text for an ad | `campaigns.search_document(description, summary)`, which is `"{description} {summary}"` |
| Embedded text for a memory | its `text` |
| How to embed | `app.core.embeddings.embed_documents(texts)`: Voyage `voyage-3.5`, 1024 dimensions, `input_type="document"`. Import it; do not reimplement it |
| Dates | BSON dates, never strings: `effective_from`, `effective_to`, `valid_from`, `valid_to`, `expires_at`, `created_at`, `ts` |
| User ids | A user's id everywhere else is `str(users._id)`: `memories.scope.user_id`, `memories.created_by`, `campaigns.created_by`, `approval.by` |
| Emails | Stored lowercase in `users.email` |
| Passwords | `app.core.security.hash_password(SEED_PASSWORD)` into `users.password_hash` |
| Ad status | `pending_review`, `approved`, `released`, `rejected`, `rolled_back`. Sales see `released` only |
| Seeded approved and released ads | `compliance.verdict = "pass"`, `compliance.checked_fundamentals = [{key, version}]`, and `approval = {by, at, ad_version, policy_versions, offer_version}` with `policy_versions` equal to `checked_fundamentals`. Release compares these with the current versions |
| Ad versions | `version` (int) and `history: []` on every ad |
| Files | GridFS with `metadata: {mime, team, uploaded_by}`. An ad's `assets` is `[{type: "audio" or "image", file_id: "<string id>", mime}]` |
| Producing seed audio and banners | `app.services.media.synthesize_bytes(text)` and `media.render_image_bytes(copy, language=..., card_name=...)` |
| Vector index names | `fundamentals_vec`, `campaigns_vec`, `memories_vec`, with the filter fields in `MONGODB_SETUP.md` |
| Search filters used | clauses: `status`, `region`, `product`. Ads: `team`, `status`. Memories: `status`, `scope.team`, `visibility_roles`, `kind` |

## For the web app owner

Base URL `http://localhost:8000`; interactive docs at `/docs`. Send `Authorization: Bearer <token>` on everything but `/auth/login`.

Differences from, and additions to, `CONTRACTS.md` as first written:

| Topic | What the backend does |
|---|---|
| Errors | Domain errors return `{ "error": "<code>", "message": "..." }`. Codes: `denied` 403, `step_up_failed` 401, `stale_approval` 409 (with `changes: [...]`), `not_approvable` 409, `stopped` 409, `not_found` 404, `unsupported_media` 415, `embedding_rate_limited` 429, `model_refused` / `model_failed` 502. Login and token failures use FastAPI's `{ "detail": "..." }` with 401 |
| Reviewing pasted copy in chat | Send the copy as `ad.text` with the rest of the ad context. A request with `ad.text` or `file_id` is always a review |
| Reviewing a library ad again | Send `ad: { campaign_id }`. The stored ad's own offer, region and channel are used |
| Approve | Only an ad that is pending review **and passed** can be approved. Anything else returns 409 `not_approvable`: regenerate first |
| Report | Adds `corrected_language`, set when the fix is to change language (an English ad for Quebec is corrected into French) |
| `memories_used` on a report | Ids of every memory that was in front of the judge. A finding that rests on one names it in its own `memory_id` |
| `memory_change` card | `{ target: "fundamental" or "memory", id, key?, kind?, scope?, before, after, action: "create" / "correct" / "forget", status: "proposed", requires_password, version? }`. To apply: `PUT /fundamentals/{id}`, `POST /memories`, `PATCH /memories/{id}` or `DELETE /memories/{id}`, with `password` and `reason` when `requires_password` is true |
| Denied in chat | `/chat` returns 200 with `status: "denied"` and a fixed reply; the refusal is on the ledger. Direct endpoints return 403 |
| Stopped in chat | `/chat` returns 200 with `status: "stopped"` |
| `/compliance/check` | Returns the report fields at the top level, plus `run_id`, `campaign` (when `save` is true), `memory_chips` and `tokens` |
| `/campaigns/{id}/regenerate` | Returns `{ status, campaign, report, attempts, reply, run_id, tokens }` |
| Run id on writes | Every write endpoint accepts an optional `run_id` and returns the one it used, so the page can call `/runs/{id}/rollback` or open `/audit/stream?run_id=` for it. `DELETE /memories/{id}` returns it in the `X-Run-Id` header |
| Ad card | `asset` is `{ type, url }` or null; fetch `url` with `?token=<jwt>` for `<img>` and `<audio>`. `text` is always present and is what was reviewed |
| Conversations | A thread is private to the user who started it |
