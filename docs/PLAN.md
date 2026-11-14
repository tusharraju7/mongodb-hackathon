# Execution plan (4 hours, 4 people)

Read [AGENTS.md](../AGENTS.md) first. Times are T+h:mm from kickoff. **P0** must be merged by T+3:00. Every task ends with a check; the task is done when the check passes.

## Team

| Stream | Scope | Person | Agent |
|---|---|---|---|
| 0 | Bootstrap (first 30 minutes) | repo owner | |
| A | Identity, policy, audit — problem statement 1 | | |
| B | Agent and compliance | | |
| C | Memory, ad library, offers, media — problem statement 2 | | |
| D | Web app | | |

Fill in names at kickoff. The Stream 0 owner then takes one of A–D.

## Scope

Three use cases, built in this order. Flows are in [FLOWS.md](FLOWS.md); one ad followed end to end is in [WORKED_EXAMPLE.md](WORKED_EXAMPLE.md).

1. **UC1** Existing creative review → regenerate a compliant version → approve → gated release
2. **UC4** Memory updates by the marketing manager
3. **UC5** General questions about an ad, returning the ad itself

Ads are **text, audio or image**, in and out. Audio is transcribed with ElevenLabs Scribe; images are read by a vision model; regenerated audio comes from ElevenLabs text-to-speech; regenerated images are rendered from a brand template in code.

Out of scope: creating creative from a blank prompt (was UC2) and comparing campaigns (was UC3). Do not build them. Do not add an image-generation model.

Setting: Tamarack Bank, a fictional Canadian bank advertising the Tamarack Cashback Card. Teams `national` and `quebec`; ad regions `CA` and `CA-QC`; amounts in CAD. The running example ad is *"Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."* against offer `TCB-FALL-2026` (0% for 10 months, then 20.99%; $300 after $1,500 in purchases in 90 days).

## Clock

| T+ | Event |
|---|---|
| 0:00–0:30 | Stream 0. Everyone else: clone, get keys, set up `.env`, read `AGENTS.md` and their stream |
| 0:30 | Scaffold on `main`. Streams A–D start |
| 1:30 | **Integration 1:** login and `/compliance/check` are real on `main` (the running example, as text, returns its findings through the API) |
| 2:30 | **Integration 2:** UC1 for text (review → regenerate → approve → release) and UC4 work end to end from the web app. Run `python -m scripts.smoke` |
| 3:00 | All P0 merged, including UC5 and audio and image in and out |
| **3:15** | **Feature freeze.** Fixes only |
| 3:15–3:45 | Reseed demo data, rehearse [DEMO.md](DEMO.md) twice |
| 3:45–4:00 | Record a backup video, finish README "Built during the hackathon", confirm the repo is public, submit |

The schedule is tight: the P0 list fills every stream to T+3:00. Build text first, then audio, then image, so that each cut below still leaves a working product.

**Cut order if behind:** P2 → P1 → Memory page (use chat to forget) → live ledger panel (poll `/audit` instead) → image regeneration → image input → audio regeneration → audio input → per-claim search (search once with the whole ad, keep the mandatory lookup) → UC5.

Never cut: the gate and ledger, the offer check, review of text ads, regenerate for text, approve and the release check, the step-up password on UC4, team-scoped recall.

---

## Stream 0 — Bootstrap (T+0:00–0:30)

One person and their agent. Goal: a runnable skeleton on `main` so four streams can work in parallel without touching each other's files.

- **S0.1 Atlas access** — follow [SETUP.md](SETUP.md): create the app database user, add teammates' IPs, share the connection string privately. *Check: every teammate can connect.*
- **S0.2 Scaffold** — create the layout in `AGENTS.md`. Include `.gitignore` (with `.env`), `.env.example` (names only), `.mcp.json`. Working pieces: `core/config.py`, `core/db.py`, login + `current_identity`, a minimal `guarded()` that writes `decision` and `outcome` events, `core/llm.py`, `core/embeddings.py`, typed `frontend/lib/api.ts` and `lib/types.ts`. Every other router and service is a stub with the exact signature from [CONTRACTS.md](CONTRACTS.md) returning a contract-shaped fixture. Pin `requirements.txt` after installing. *Check: backend starts, `/auth/login` works, frontend starts and shows the login page.*
- **S0.3 Database** — follow [MONGODB_SETUP.md](MONGODB_SETUP.md) steps 2 to 5: `scripts/setup_db.py` (nine collections with validators, regular + TTL + vector indexes; idempotent) and `scripts/seed.py` loading the reference data from `backend/seed/` (`policies`, `users`, `offers`, the 18 policy clauses with embeddings, and their earlier versions). *Check: the three vector indexes are READY; a `$vectorSearch` on `fundamentals` for "guaranteed approval" returns `credit.approval_claims` first.*
- **S0.4 Push to `main`** and tell the team. *Check: a teammate clones, copies `.env`, and both apps start.*

---

## Stream A — Identity, policy, audit

Owns: `core/{security,gate}.py`, `routers/{auth,fundamentals,audit,runs}.py`, `services/fundamentals.py`, `scripts/setup_db.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| A1 | 0:30–1:00 | P0 | Harden the gate: permissions read from `policies`, stop-flag check on `runs`, `decision` and `outcome` events with `policy_refs`, `memories_used`, `undo`, `auth.method`. `Denied` → 403, `RunStopped` → run `stopped` | A sales token calling a review, a regeneration, an approval or a memory write gets 403 and a `deny` event exists in `ledger` |
| A2 | 1:00–1:20 | P0 | `$jsonSchema` validators on `ledger`, `memories`, `fundamentals` in `setup_db.py` | Inserting a ledger event with no `actor` is rejected by MongoDB |
| A3 | 1:20–2:00 | P0 | Policy clauses: `list_all`; `retrieve` (per-query vector search filtered by product, regions, `approved`, effective dates); `mandatory` (by claim type); `hard_rules`; `current_versions`. Update with step-up password, snapshot to `fundamentals_versions`, version + 1, re-embed, ledger event with before/after and reason; history endpoint | Missing or wrong password → 401 and a `deny` event. Correct password → version + 1, snapshot stored, `auth.method = jwt+password`. A `retired` or out-of-date clause is never returned by `retrieve` or `mandatory` |
| A4 | 2:00–2:30 | P0 | `GET /audit` with filters; `/audit/stream` backed by a change stream on `ledger`; `POST /runs/{id}/stop` | Events appear in the stream while a review runs; Stop during a regeneration halts it before the file is rendered |
| A5 | 2:30–3:00 | P1 | `POST /runs/{id}/rollback`: replay `undo` descriptors in reverse (policy → previous version restored; memory change → new one forgotten and the superseded one reactivated; submitted or regenerated ad version → `rolled_back` and its file removed), write `rollback` events | Rolling back a policy edit restores the previous version and text. Rolling back a regeneration removes the new version and its file |
| A6 | after | P2 | Database-level append-only: custom role with insert + find only on `ledger`; hash-chained events | An update on `ledger` from the app user fails |

## Stream B — Agent and compliance

Owns: `agent/*`, `services/compliance.py`, `routers/{chat,compliance}.py`, `core/llm.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| B1 | 0:30–1:20 | P0 | Compliance engine (UC1), in this order: load the offer (`offers.get`; none → `missing_inputs`, stop); `extract_claims` on the fast model; checks in code (budget cap, banned terms, required lines, claim values against the offer); `fundamentals.retrieve` with one vector per claim plus `fundamentals.mandatory` for the claim types, deduplicated, at most 8; `memory.recall` top 3 (procedural + episodic) unless `use_memory=false`; main-model judge with structured output, including `corrected_copy`, and taking `visual_notes` into account for image ads. The judge returns, per finding, a quote, a two-sentence `reasoning`, `evidence` and a `certainty` label, plus a three-sentence `summary`. Then in code: drop findings whose quote is not in the ad, score confidence per finding and for the verdict with the formula in CONTRACTS, build `passed_checks`, choose the route. Expose `POST /compliance/check`, gated by `compliance.check` | The running example returns `blocked`, route `human_review`, with findings citing `credit.approval_claims`, `policy.offer_accuracy` (12 vs 10 months), `credit.intro_rate_disclosure`, `credit.bonus_conditions`, `regional.ca.email_consent` and `brand.required_footer`. The offer-mismatch finding has `basis: "code"` and confidence 100; the approval finding scores 95 with its reasons listed; verdict confidence is high. A finding with a made-up quote is dropped. An unknown `offer_id` returns `missing_inputs` and no verdict |
| B2 | 1:20–1:50 | P0 | Front door: intent router on the fast model, offered only the intents the role may use (`review`, `memory_update`, `ask`). Per-intent, per-role tool sets. Identity and `run_id` bound by closure. `MongoDBSaver` checkpointer; last 6 turns + summary to the model. `POST /chat` returns reply, cards, `memories_used`, tokens. `review_creative` tool: for a file, `media.transcribe` or `media.read_image` first; then `compliance.check`, `campaigns.submit`, episodic `remember`; each step its own `guarded()` call | Sales asking to change a policy gets the fixed denial, a `deny` event, and no further model call. A marketer review request returns a `compliance_report` card and the ad appears in the library as `pending_review` |
| B3 | 1:50–2:15 | P0 | `compliance.regenerate` and the `regenerate_creative` tool, gated by `asset.regenerate`: take `corrected_copy`; `check` it; if not a pass, one repair on the main model and `check` again; still not a pass → `failed`, nothing rendered or saved. On a pass, render by modality (`media.synthesize_speech`, `media.render_image`, or the copy itself) and `campaigns.submit` as the next version with `source: "regenerated"` | Regenerating the running example yields version 2 that passes. A copy that cannot be made to pass returns `failed` with the remaining findings, and no file or version is created. With media stubs it works for text; with C4 merged it returns audio for an audio ad |
| B4 | 2:15–2:40 | P0 | UC4 tools: `update_memory` and `forget_memory` draft the change on the fast model and return a `memory_change` card with `status: "proposed"`. They do not write; the web app calls the write endpoints with the password | "From now on, Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'" returns a proposed procedural memory scoped to the Quebec team. After it is applied, re-reviewing a Quebec ad without that line is flagged citing the memory id; with `use_memory=false` it is not |
| B5 | 2:40–3:00 | P0 | UC5 `ask_about_ad`: thread reference first, else top-1 `campaigns.search`; answer from `facts`, `summary` and the offer record; load `text` only if needed; never state a term absent from the ad and the offer; return the ad's card so the image or audio is shown; return `grounding` (sources and band) | "A customer got an email about $300 cash back, what are the conditions?" returns the released ad's card and the offer's spend, deadline and rates. "Show me the banner about cash back" returns an image ad. Sales never receive an unreleased ad |
| B6 | after | P1 | Stored-report reuse (`cache_key`); token logging on `runs` | Second review of the same ad returns `cached: true`; after a policy edit or a new team instruction it does not |
| B7 | after | P1 | Round-trip check on regenerated audio: transcribe the new file and confirm it matches the approved copy | A regenerated audio ad's transcript equals its `text` after normalisation |
| B8 | after | P1 | `review_fundamentals`: gaps, conflicts, suggestions over all clause summaries | Returns a `fundamentals_review` card |
| B9 | after | P2 | Runtime MongoDB MCP tool (read-only) for manager questions such as "what was blocked this week?" | |

## Stream C — Memory, ad library, offers, media

Owns: `services/{memory,campaigns,offers,media}.py`, `routers/{campaigns,assets,memories}.py`, `core/embeddings.py`, `scripts/seed.py`, `seed/*`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| C1 | 0:30–1:00 | P0 | Demo seed, [MONGODB_SETUP.md](MONGODB_SETUP.md) step 6, from `backend/seed/campaigns.json` and `memories.json`: the 9 card ads (text, audio and image; English and French; released, approved, pending and rejected) with embeddings and approvals; the 9 memories with scope and expiry; a ledger event pair for each seeded approval and release. Audio and image files are added by re-running the seed once C4 and C5 exist | The step 7 verification table passes, apart from the media rows until C4 and C5 land |
| C2 | 1:00–1:40 | P0 | Ad library: `submit` (new ad, or next version when `campaign_id` is given; clears `approval`; embed; `pending_review`), `search` (vector + team and role/status pre-filter), `get`, `approve` (stores ad version, policy versions, offer version), `reject` (feedback becomes a procedural memory), `release` (compares the approval with current versions via `fundamentals.current_versions` and the offer; mismatch → `StaleApproval`, deny event, back to `pending_review`); `/campaigns` and `/offers` endpoints; `POST /assets` and `GET /assets/{file_id}` for audio and images; `media.store` | A sales search returns only released ads of their team. Release of an approved ad succeeds; after one of its policies is edited, release returns 409 naming the policy and versions |
| C3 | 1:40–2:15 | P0 | Memory service: `remember`, `recall` (scoped pre-filter, expiry filter, `use_count` bump), `correct` (supersede), `forget` (tombstone), all through `guarded()`; `/memories` endpoints with step-up for team scope | A national-team user's recall never returns a Quebec memory. A forgotten or expired memory is not recalled. A corrected memory returns only the new text |
| C4 | 2:15–2:40 | P0 | Audio in and out: `media.transcribe` with ElevenLabs Scribe and `media.synthesize_speech` with ElevenLabs text-to-speech (stock voice, English and French) | Uploading a seeded French radio spot returns its transcript. `synthesize_speech` returns a file id that plays as `audio/mpeg` |
| C5 | 2:40–3:00 | P0 | Image in and out: `media.read_image` (fast model with image input → all on-image text including fine print, plus `visual_notes`) and `media.render_image` (brand template in code → PNG) | Reading a seeded banner returns its headline and fine print. `render_image` returns a PNG that shows the copy legibly, fine print included |
| C6 | after | P2 | Read UC5 answers aloud with ElevenLabs text-to-speech. Image search with Voyage multimodal embeddings in a separate index | |

## Stream D — Web app

Owns: `frontend/**`, `docs/DEMO.md`. Works against the scaffold's fixtures until real endpoints land; no backend edits.

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| D1 | 0:30–1:00 | P0 | Login, auth context, role-aware navigation (sales: Chat and Library only; marketer: + Policies read-only and Memory; manager: everything) | Three seeded users log in and see different navigation |
| D2 | 1:00–2:00 | P0 | Chat: message list; paste text or attach an audio or image file; ad context form (offer picker, region, channel, budget); compliance report card (verdict, overall confidence with its reasons, summary, route badge with its reason; each finding with the cited policy and version, offer or memory, the fix, its confidence, and reasoning and evidence on expand; what passed; corrected copy; **Regenerate compliant version**); ad card that shows the ad in its own form (image, audio player or text) plus the reviewed text; memory chips under replies; live run ledger side panel with **Stop** | The running example can be reviewed and regenerated from the chat page; ledger events appear while the request runs |
| D3 | 2:00–2:30 | P0 | Library: grid with image thumbnails and audio players, status filter, version history showing regenerated versions next to the one they correct, **Approve** / **Reject** with feedback (manager), **Release** with the stale-approval message. UC4: `memory_change` card showing before/after, with password + reason prompt on confirm. **Replay without memory** on a review reply, side by side | Release shows which policy changed when the approval is stale. A manager instruction is confirmed with a password every time; replay shows a different verdict |
| D4 | 2:30–3:00 | P0 | Policies: list, edit modal with password + reason, version history. Audit: timeline filtered by run or actor, **Rollback**. Memory: scoped list with kind, scope, expiry; correct and forget | A policy edit prompts for the password and shows the new version |
| D5 | after | P1 | Tokens per run in the audit view | |

---

## Verification

`backend/scripts/smoke.py` (run at 2:30 and at freeze) asserts against the shared cluster:

- Three role logins succeed.
- Sales calling a review, a regeneration, an approval or a memory write → 403 and a `deny` event.
- The running example → `blocked`, `human_review`, the six expected citations.
- Every report has a `summary`, a verdict `confidence` with reasons, and `reasoning`, `evidence` and `confidence` on each finding. Code findings score 100 on text input; model findings never exceed 95; the same ad read from an image scores lower.
- A pass with confidence below 80 is routed to `human_review`.
- Regenerating it → `regenerated`, a new version with `source: "regenerated"` whose report is `pass`. A forced failing copy → `failed`, no new version, no new file.
- Unknown offer → `missing_inputs`, no verdict; regeneration refused.
- An uploaded audio ad is transcribed and reviewed; regenerating it returns a playable audio file. An uploaded image ad is read and reviewed; regenerating it returns a PNG.
- An English-only `CA-QC` ad cites `regional.qc.french_language`; the same ad with region `CA` does not.
- Approve stores the ad version and policy versions. Release succeeds; after a policy edit, release of another approved ad → 409 and the ad is `pending_review`.
- Sales can find an ad only after it is released, and receive its image or audio.
- Policy update without password → 401; with password → version + 1, snapshot, ledger event with `jwt+password`.
- After the Quebec team instruction, the affected ad is flagged citing the memory id; with `use_memory=false` it is not.
- Cross-team recall returns nothing; a forgotten memory is not recalled.
- Stop → run `stopped`. Rollback of a policy edit → previous version restored.

Spot checks through the MongoDB MCP server: the three vector indexes are READY; the events for one `run_id`, sorted by `ts`, reconstruct the run.

Manual: run [DEMO.md](DEMO.md) end to end twice, on two different laptops.
