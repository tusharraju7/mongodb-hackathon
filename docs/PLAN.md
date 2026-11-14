# Execution plan (4 hours, 4 people)

Read [AGENTS.md](../AGENTS.md) first. Times are T+h:mm from kickoff. **P0** must be merged by T+2:30. Every task ends with a check; the task is done when the check passes.

## Team

| Stream | Scope | Person | Agent |
|---|---|---|---|
| 0 | Bootstrap (first 30 minutes) | repo owner | |
| A | Identity, policy, audit — problem statement 1 | | |
| B | Agent and compliance | | |
| C | Memory, retrieval, generation — problem statement 2 | | |
| D | Web app | | |

Fill in names at kickoff. The Stream 0 owner then takes one of A–D.

## Use-case priority

Build in this order; if time runs out, the later ones are cut first.

1. UC1 Existing creative review
2. UC2 New creative from a prompt
3. UC3 Comparing current campaigns
4. UC4 Memory updates by the marketing manager
5. UC5 General questions about an ad

Flows for each are in [FLOWS.md](FLOWS.md).

## Clock

| T+ | Event |
|---|---|
| 0:00–0:30 | Stream 0. Everyone else: clone, get keys, set up `.env`, read `AGENTS.md` and their stream |
| 0:30 | Scaffold on `main`. Streams A–D start |
| 1:15 | **Integration 1:** login and `/compliance/check` are real on `main` (UC1 works through the API) |
| 2:30 | **Integration 2:** all P0 merged. Run `python -m scripts.smoke` |
| 2:30–3:15 | Remaining P0 polish, then P1 |
| **3:15** | **Feature freeze.** Fixes only |
| 3:15–3:45 | Reseed demo data, rehearse [DEMO.md](DEMO.md) twice |
| 3:45–4:00 | Record a backup video, finish README "Built during the hackathon", confirm the repo is public, submit |

**Cut order if behind:** P2 → P1 → Memory page (use chat to forget) → live SSE panel (poll `/audit` instead) → Library approve UI (seed approved campaigns) → UC5 → UC3.

---

## Stream 0 — Bootstrap (T+0:00–0:30)

One person and their agent. Goal: a runnable skeleton on `main` so four streams can work in parallel without touching each other's files.

- **S0.1 Atlas access** — follow [SETUP.md](SETUP.md): create the app database user, add teammates' IPs, share the connection string privately. *Check: every teammate can connect.*
- **S0.2 Scaffold** — create the layout in `AGENTS.md`. Include `.gitignore` (with `.env`), `.env.example` (names only), `.mcp.json`. Working pieces: `core/config.py`, `core/db.py`, login + `current_identity`, a minimal `guarded()` that writes `decision` and `outcome` events, `core/llm.py`, `core/embeddings.py`, typed `frontend/lib/api.ts` and `lib/types.ts`. Every other router and service is a stub with the exact signature from [CONTRACTS.md](CONTRACTS.md) returning a contract-shaped fixture. Pin `requirements.txt` after installing. *Check: backend starts, `/auth/login` works, frontend starts and shows the login page.*
- **S0.3 Database** — `scripts/setup_db.py` (collections, validators, regular + TTL + vector indexes; idempotent) and a minimal `scripts/seed.py` (6 users: 3 roles × 2 teams; `policies`; the 14 fundamentals with summaries and embeddings). *Check: the three vector indexes are READY; a `$vectorSearch` on `fundamentals` returns results.*
- **S0.4 Push to `main`** and tell the team. *Check: a teammate clones, copies `.env`, and both apps start.*

---

## Stream A — Identity, policy, audit

Owns: `core/{security,gate}.py`, `routers/{auth,fundamentals,audit,runs}.py`, `services/fundamentals.py`, `scripts/setup_db.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| A1 | 0:30–1:00 | P0 | Harden the gate: RBAC read from `policies`, stop-flag check on `runs`, `decision` and `outcome` events with `policy_refs`, `memories_used`, `undo`, `auth.method`. `Denied` → 403, `RunStopped` → run `stopped` | A sales token calling a generate action gets 403 and a `deny` event exists in `ledger` |
| A2 | 1:00–1:20 | P0 | `$jsonSchema` validators on `ledger`, `memories`, `fundamentals` in `setup_db.py` | Inserting a ledger event with no `actor` is rejected by MongoDB |
| A3 | 1:20–2:00 | P0 | Fundamentals (UC4): list; `retrieve` and `hard_rules` for the compliance engine; update with step-up password, snapshot to `fundamentals_versions`, version + 1, re-embed, ledger event with before/after and reason; history endpoint | Missing or wrong password → 401 and a `deny` event. Correct password → version + 1, snapshot stored, `auth.method = jwt+password` |
| A4 | 2:00–2:30 | P0 | `GET /audit` with filters; `/audit/stream` SSE backed by a change stream on `ledger`; `POST /runs/{id}/stop` | Events appear in the stream while a generation runs; Stop halts it before the next step |
| A5 | 2:30–3:00 | P1 | `POST /runs/{id}/rollback`: replay `undo` descriptors in reverse, write `rollback` events | After rollback the campaign is `rolled_back`, its audio is gone, its episodic memory is `forgotten` |
| A6 | after | P1 | Change stream on `fundamentals` that clears `compliance.cache_key` on campaigns citing the changed key | Re-review after a fundamentals edit is not served from cache |
| A7 | after | P2 | Database-level append-only: custom role with insert + find only on `ledger`; hash-chained events | An update on `ledger` from the app user fails |

## Stream B — Agent and compliance

Owns: `agent/*`, `services/compliance.py`, `routers/{chat,compliance}.py`, `core/llm.py`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| B1 | 0:30–1:15 | P0 | Compliance engine (UC1): hard rules in code first (budget cap, voice allow-list, banned terms, required line); `fundamentals.retrieve` top 5 for region ∈ {global, ad region}; episodic recall top 3; fast-model judge with structured output → `ComplianceReport`. Expose `POST /compliance/check`, gated by `compliance.check` | A brief with a superlative claim, a €50k budget and a celebrity voice returns three violations citing three different fundamentals with versions |
| B2 | 1:15–2:00 | P0 | Front door: intent router on the fast model, offered only the intents the role may use. Per-intent, per-role tool sets (`review_creative`, `generate_ad`, `compare_campaigns`, `ask_about_ad`, `update_memory`, `forget_memory`). Identity and `run_id` bound by closure. `MongoDBSaver` checkpointer; last 6 turns + summary to the model. `POST /chat` returns reply, cards, `memories_used`, tokens | Sales asking to create an ad gets the fixed denial, a `deny` event, and no script-writing model call. A marketer review request returns a `compliance_report` card |
| B3 | 2:00–2:30 | P0 | `generate_ad` (UC2): pre-check → not a pass: return violations, run `blocked`, nothing generated; pass: recall procedural + preferences, write script on the main model, post-check, `create_voiceover`, `campaigns.create`, episodic `remember`. Each step its own `guarded()` call | Non-compliant brief creates no campaign and spends no ElevenLabs credits. Compliant brief yields a `campaign` card with playable audio and non-empty `memories_used` when a procedural memory applies |
| B4 | 2:30–3:00 | P0 | `compare_campaigns` (UC3): table built in code from `facts`, short takeaway. `ask_about_ad` (UC5): thread reference first, else top-1 search; facts first, script only if needed. `update_memory` / `forget_memory` (UC4) call C's memory service and A's fundamentals service with step-up | Compare returns a `comparison` card for two seeded campaigns. "What is the CTA in the train-station ad?" answers and returns that campaign's card. Sales never receive a non-approved campaign |
| B5 | after | P1 | Compliance report cache (`cache_key` = hash of text + consulted fundamentals versions); token logging on `runs`; `use_memory=false` replay path | Second review of the same ad returns `cached: true`. Replay returns empty `memories_used` |
| B6 | after | P1 | `review_fundamentals`: gaps, conflicts, suggestions over all summaries | Returns a `fundamentals_review` card |
| B7 | after | P2 | Runtime MongoDB MCP tool (read-only) for manager questions such as "what was blocked this week?" | |

## Stream C — Memory, retrieval, generation

Owns: `services/{memory,campaigns,generation}.py`, `routers/{campaigns,assets,memories}.py`, `core/embeddings.py`, `scripts/seed.py`, `seed/*`

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| C1 | 0:30–1:00 | P0 | Full seed: 6 approved + 2 pending campaigns across both teams with real ElevenLabs audio, `summary`, `facts`, embeddings; memories for both teams (procedural, semantic, episodic), including one that expires a few minutes after seeding | Library data is visible in Atlas; seeded audio plays from `/assets/{file_id}` |
| C2 | 1:00–1:40 | P0 | Generation and campaigns: ElevenLabs TTS → GridFS; `/assets/{file_id}`; `create` (extract `summary` + `facts` once on the fast model, embed), `search` (vector + team and role/status pre-filter), `get`, `set_status` (approve/reject; feedback becomes a procedural memory) | A sales search returns only approved campaigns of their team. `create_voiceover` returns a file id that streams as `audio/mpeg` |
| C3 | 1:40–2:30 | P0 | Memory service: `remember`, `recall` (scoped pre-filter, expiry filter, `use_count` bump), `correct` (supersede), `forget` (tombstone), all through `guarded()`; `/memories` endpoints with step-up for team scope | A US-team user's recall never returns an EMEA memory. A forgotten or expired memory is not recalled. A corrected memory returns only the new text |
| C4 | after | P1 | ElevenLabs Scribe: upload an audio ad → transcript → UC1 | An uploaded mp3 yields a compliance report |
| C5 | after | P2 | Eleven Music bed under the voiceover; ffmpeg still image + voiceover → mp4 | |

## Stream D — Web app

Owns: `frontend/**`, `docs/DEMO.md`. Works against the scaffold's fixtures until real endpoints land; no backend edits.

| Id | When | Pri | Task | Check |
|---|---|---|---|---|
| D1 | 0:30–1:00 | P0 | Login, auth context, role-aware navigation (sales: Chat and Library only; marketer: + Fundamentals read-only and Memory; manager: everything) | Three seeded users log in and see different navigation |
| D2 | 1:00–2:00 | P0 | Chat: message list; cards for compliance report (violations with cited fundamental, version, fix), campaign (audio player), comparison (table + takeaway), memory change; memory chips under replies; live run ledger side panel (SSE) with **Stop** | UC1 and UC2 can be driven from the chat page; ledger events appear while the request runs |
| D3 | 2:00–2:30 | P0 | Library: grid, status filter, approve / reject with feedback (manager) | Sales see approved only; manager approval changes status |
| D4 | 2:30–3:00 | P0 | Fundamentals: list, edit modal with password + reason, version history. Audit: timeline filtered by run or actor, **Rollback**. Memory: scoped list with kind, scope, expiry; correct and forget | A fundamentals edit prompts for the password every time and shows the new version |
| D5 | after | P1 | "Replay without memory" side-by-side on a chat reply; tokens per run in the audit view | |

---

## Verification

`backend/scripts/smoke.py` (run at 2:30 and at freeze) asserts against the shared cluster:

- Three role logins succeed.
- Sales generate → 403 and a `deny` event.
- Non-compliant brief → `blocked`, at least one cited fundamental, no campaign created.
- Compliant brief → campaign with a GridFS file that streams as `audio/mpeg`.
- Sales search finds a campaign only after it is approved.
- Fundamentals update without password → 401; with password → version + 1, snapshot, ledger event with `jwt+password`.
- Cross-team recall returns nothing; a forgotten memory is not recalled.
- `use_memory=false` returns empty `memories_used`.
- Stop → run `stopped`. Rollback → campaign `rolled_back`.

Spot checks through the MongoDB MCP server: the three vector indexes are READY; the events for one `run_id`, sorted by `ts`, reconstruct the run.

Manual: run [DEMO.md](DEMO.md) end to end twice, on two different laptops.
