# Execution plan (4 hours, 4 people)

Read [AGENTS.md](../AGENTS.md) first. Times are T+h:mm from kickoff. **P0** must be merged by T+3:00. Every task ends with a check; the task is done when the check passes.

## Team

| Stream | Scope | Person | Agent |
|---|---|---|---|
| 0 | Bootstrap (first 30 minutes) | repo owner | |
| A | Identity, policy, audit — problem statement 1 | | |
| B | Agent and compliance | | |
| C | Memory, ad library, audio — problem statement 2 | | |
| D | Web app | | |

Fill in names at kickoff. The Stream 0 owner then takes one of A–D.

## Scope

Three use cases, built in this order. Flows are in [FLOWS.md](FLOWS.md).

1. **UC1** Existing creative review
2. **UC4** Memory updates by the marketing manager
3. **UC5** General questions about an ad

Out of scope: creating new creative from a prompt (was UC2) and comparing campaigns (was UC3). Do not build them.

Examples and seed data are Canadian: Solstice Coffee Co., a fictional Canadian roaster with a `national` team and a `quebec` team; ad regions `CA` and `CA-QC`; budgets in CAD.

## Clock

| T+ | Event |
|---|---|
| 0:00–0:30 | Stream 0. Everyone else: clone, get keys, set up `.env`, read `AGENTS.md` and their stream |
| 0:30 | Scaffold on `main`. Streams A–D start |
| 1:15 | **Integration 1:** login and `/compliance/check` are real on `main` (UC1 works through the API for pasted text) |
| 2:30 | **Integration 2:** UC1 and UC4 work end to end from the web app. Run `python -m scripts.smoke` |
| 3:00 | All P0 merged, including UC5 and audio review |
| **3:15** | **Feature freeze.** Fixes only |
| 3:15–3:45 | Reseed demo data, rehearse [DEMO.md](DEMO.md) twice |
| 3:45–4:00 | Record a backup video, finish README "Built during the hackathon", confirm the repo is public, submit |

**Cut order if behind:** P2 → P1 → Memory page (use chat to forget) → live ledger panel (poll `/audit` instead) → audio upload (review pasted text only) → Library approve UI (seed approved ads).

---

## Stream 0 — Bootstrap (T+0:00–0:30)

One person and their agent. Goal: a runnable skeleton on `main` so four streams can work in parallel without touching each other's files.

- **S0.1 Atlas access** — follow [SETUP.md](SETUP.md): create the app database user, add teammates' IPs, share the connection string privately. *Check: every teammate can connect.*
- **S0.2 Scaffold** — create the layout in `AGENTS.md`. Include `.gitignore` (with `.env`), `.env.example` (names only), `.mcp.json`. Working pieces: `core/config.py`, `core/db.py`, login + `current_identity`, a minimal `guarded()` that writes `decision` and `outcome` events, `core/llm.py`, `core/embeddings.py`, typed `frontend/lib/api.ts` and `lib/types.ts`. Every other router and service is a stub with the exact signature from [CONTRACTS.md](CONTRACTS.md) returning a contract-shaped fixture. Pin `requirements.txt` after installing. *Check: backend starts, `/auth/login` works, frontend starts and shows the login page.*
- **S0.3 Database** — `scripts/setup_db.py` (collections, validators, regular + TTL + vector indexes; idempotent) and a minimal `scripts/seed.py` (6 users: 3 roles × 2 teams; `policies`; the 16 fundamentals with summaries and embeddings). *Check: the three vector indexes are READY; a `$vectorSearch` on `fundamentals` returns results.*
- **S0.4 Push to `main`** and tell the team. *Check: a teammate clones, copies `.env`, and both apps start.*

---

## Stream A — Identity, policy, audit

Owns: `core/{security,gate}.py`, `routers/{auth,fundamentals,audit,runs}.py`, `services/fundamentals.py`, `scripts/setup_db.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| A1 | 0:30–1:00 | P0 | Harden the gate: permissions read from `policies`, stop-flag check on `runs`, `decision` and `outcome` events with `policy_refs`, `memories_used`, `undo`, `auth.method`. `Denied` → 403, `RunStopped` → run `stopped` | A sales token calling a memory or fundamentals write gets 403 and a `deny` event exists in `ledger` |
| A2 | 1:00–1:20 | P0 | `$jsonSchema` validators on `ledger`, `memories`, `fundamentals` in `setup_db.py` | Inserting a ledger event with no `actor` is rejected by MongoDB |
| A3 | 1:20–2:00 | P0 | Fundamentals (UC4): list; `retrieve` and `hard_rules` by region list for the compliance engine; update with step-up password, snapshot to `fundamentals_versions`, version + 1, re-embed, ledger event with before/after and reason; history endpoint | Missing or wrong password → 401 and a `deny` event. Correct password → version + 1, snapshot stored, `auth.method = jwt+password` |
| A4 | 2:00–2:30 | P0 | `GET /audit` with filters; `/audit/stream` backed by a change stream on `ledger`; `POST /runs/{id}/stop` | Events appear in the stream while an audio review runs; Stop halts it before the next step |
| A5 | 2:30–3:00 | P1 | `POST /runs/{id}/rollback`: replay `undo` descriptors in reverse (fundamental → previous version restored; memory change → new one forgotten and the superseded one reactivated; submitted ad → `rolled_back`), write `rollback` events | Rolling back a budget-cap edit restores the previous version and text |
| A6 | after | P2 | Database-level append-only: custom role with insert + find only on `ledger`; hash-chained events | An update on `ledger` from the app user fails |

## Stream B — Agent and compliance

Owns: `agent/*`, `services/compliance.py`, `routers/{chat,compliance}.py`, `core/llm.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| B1 | 0:30–1:15 | P0 | Compliance engine (UC1): hard rules in code first (budget cap, banned terms, required line); `fundamentals.retrieve` top 5 for `regions_for(ad region)`; `memory.recall` top 3 (procedural + episodic) unless `use_memory=false`; main-model judge with structured output → `ComplianceReport`, each violation citing a rule key + version or a memory id. Expose `POST /compliance/check`, gated by `compliance.check` | A national ad saying "Canada's best coffee, 100% Product of Canada" with a CAD 50,000 budget returns violations citing `policy.claims_substantiation`, `regional.ca.origin_claims` and `budget.cap.national`. An English-only ad with region `CA-QC` cites `regional.qc.french_language` |
| B2 | 1:15–2:00 | P0 | Front door: intent router on the fast model, offered only the intents the role may use (`review`, `memory_update`, `ask`). Per-intent, per-role tool sets. Identity and `run_id` bound by closure. `MongoDBSaver` checkpointer; last 6 turns + summary to the model. `POST /chat` returns reply, cards, `memories_used`, tokens. `review_creative` tool: optional `audio.transcribe`, `compliance.check`, `campaigns.submit` for new creative, episodic `remember`; each step its own `guarded()` call | Sales asking to change a rule gets the fixed denial, a `deny` event, and no further model call. A marketer review request returns a `compliance_report` card |
| B3 | 2:00–2:30 | P0 | UC4 tools: `update_memory` and `forget_memory` draft the change on the fast model and return a `memory_change` card with `status: "proposed"`. They do not write; the web app calls the write endpoints with the password | "From now on, Quebec audio ads must end with 'Torréfié au Québec'" returns a proposed procedural memory scoped to the Quebec team. After it is applied, re-reviewing a Quebec audio ad without that line is flagged citing the memory id; with `use_memory=false` it is not |
| B4 | 2:30–3:00 | P0 | UC5 `ask_about_ad`: thread reference first, else top-1 `campaigns.search`; answer from `facts` and `summary`, load `text` only if needed | "I heard an ad about slow mornings at Union Station, what's the offer?" answers and returns that ad's card. Sales never receive a non-approved ad |
| B5 | after | P1 | Stored-report reuse (`cache_key`); token logging on `runs` | Second review of the same ad returns `cached: true`; after a new team instruction it does not |
| B6 | after | P1 | `review_fundamentals`: gaps, conflicts, suggestions over all rule summaries | Returns a `fundamentals_review` card |
| B7 | after | P2 | Runtime MongoDB MCP tool (read-only) for manager questions such as "what was blocked this week?" | |

## Stream C — Memory, ad library, audio

Owns: `services/{memory,campaigns,audio}.py`, `routers/{campaigns,assets,memories}.py`, `core/embeddings.py`, `scripts/seed.py`, `seed/*`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| C1 | 0:30–1:00 | P0 | Full seed: 8 ads across both teams (6 approved, 2 pending), English and French, with audio produced by ElevenLabs text-to-speech, `text`, `summary`, `facts`, embeddings. Memories for both teams (procedural, semantic, episodic), including one that expires a few minutes after seeding | Ads are visible in Atlas; seeded audio plays from `/assets/{file_id}` |
| C2 | 1:00–1:40 | P0 | Ad library: `submit` (extract `summary` + `facts` once on the fast model, embed, save `pending_review`), `search` (vector + team and role/status pre-filter), `get`, `set_status` (approve/reject; feedback becomes a procedural memory); `/campaigns` endpoints; `POST /assets` upload to GridFS and `GET /assets/{file_id}` | A sales search returns only approved ads of their team. An uploaded mp3 streams back as `audio/mpeg` |
| C3 | 1:40–2:30 | P0 | Memory service: `remember`, `recall` (scoped pre-filter, expiry filter, `use_count` bump), `correct` (supersede), `forget` (tombstone), all through `guarded()`; `/memories` endpoints with step-up for team scope | A national-team user's recall never returns a Quebec memory. A forgotten or expired memory is not recalled. A corrected memory returns only the new text |
| C4 | 2:30–3:00 | P0 | `audio.transcribe` with ElevenLabs Scribe, English and French | Uploading a seeded French ad returns its transcript, and UC1 produces a compliance report from it |
| C5 | after | P2 | Read UC5 answers aloud with ElevenLabs text-to-speech | |

## Stream D — Web app

Owns: `frontend/**`, `docs/DEMO.md`. Works against the scaffold's fixtures until real endpoints land; no backend edits.

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| D1 | 0:30–1:00 | P0 | Login, auth context, role-aware navigation (sales: Chat and Library only; marketer: + Fundamentals read-only and Memory; manager: everything) | Three seeded users log in and see different navigation |
| D2 | 1:00–2:00 | P0 | Chat: message list; paste text or attach an audio file; region, channel and budget fields for a review; cards for compliance report (violations with the cited rule and version or memory, and the fix) and ad (audio player); memory chips under replies; live run ledger side panel with **Stop** | UC1 can be driven from the chat page; ledger events appear while the request runs |
| D3 | 2:00–2:30 | P0 | UC4: `memory_change` card showing the before/after, with password + reason prompt on confirm, calling the write endpoint. **Replay without memory** on a review reply, side by side | A manager instruction is confirmed with a password every time; replay shows a different verdict |
| D4 | 2:30–3:00 | P0 | Library: grid, status filter, approve / reject with feedback (manager). Fundamentals: list, edit modal with password + reason, version history. Audit: timeline filtered by run or actor, **Rollback**. Memory: scoped list with kind, scope, expiry; correct and forget | Sales see approved ads only. A fundamentals edit prompts for the password and shows the new version |
| D5 | after | P1 | Tokens per run in the audit view | |

---

## Verification

`backend/scripts/smoke.py` (run at 2:30 and at freeze) asserts against the shared cluster:

- Three role logins succeed.
- Sales calling a review or a memory write → 403 and a `deny` event.
- The "Canada's best coffee, 100% Product of Canada, CAD 50,000" ad → not a pass, with the three expected rules cited.
- An English-only `CA-QC` ad cites `regional.qc.french_language`; the same ad with region `CA` does not.
- A compliant new ad is saved as `pending_review`; sales can find it only after it is approved.
- Fundamentals update without password → 401; with password → version + 1, snapshot, ledger event with `jwt+password`.
- After a new Quebec team instruction, the affected ad is flagged citing the memory id; with `use_memory=false` it is not.
- Cross-team recall returns nothing; a forgotten memory is not recalled.
- An uploaded audio ad is transcribed and reviewed.
- Stop → run `stopped`. Rollback of a fundamentals edit → previous version restored.

Spot checks through the MongoDB MCP server: the three vector indexes are READY; the events for one `run_id`, sorted by `ts`, reconstruct the run.

Manual: run [DEMO.md](DEMO.md) end to end twice, on two different laptops.
