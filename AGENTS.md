# AGENTS.md — guidance for every coding agent in this repo

This file is the single source of guidance for Claude Code, Codex, and any other agent. `CLAUDE.md` only imports it. Read this file fully, then the doc for your task.

## What we are building

**Greenlight**: a governed marketing agent for an organisation, built in a 4-hour hackathon by a team of 4.

- Three use cases, in priority order:
  - **UC1** Review existing ad creative against policy clauses and the approved offer record; route it; on request regenerate a compliant version; a manager approves; release is gated on that approval still being current.
  - **UC4** Let the marketing manager update what the agent knows and remembers.
  - **UC5** Answer questions about an ad, returning the ad itself.
- Ads are text, audio or image, in and out. Audio in: ElevenLabs Scribe. Image in: the fast model with image input. Audio out: ElevenLabs text-to-speech. Image out: a brand template rendered in code.
- Out of scope: creating creative from a blank prompt (was UC2) and comparing campaigns (was UC3). Do not build them.
- Data set: **NorthPlay**, a fictional Ontario sportsbook (`northplay-demo-data/`): 15 advertising regulations, 15 past ad decisions, Slack decisions that are binding and stricter than the regulations, and strategy decks that are partly out of date. The backend and the `greenlight` database run on it; see [docs/BACKEND.md](docs/BACKEND.md).
- The older docs (`FLOWS.md`, `WORKED_EXAMPLE.md`, parts of `CONTRACTS.md`, `DEMO.md`) explain the same mechanisms with an earlier fictional-bank example. The offline tests still use that example as fixtures.
- Every action is tied to an identity, checked against policy **before** it runs, and recorded in a ledger. Runs can be stopped and rolled back. (Problem statement 1: *Agents You Can Audit*.)
- Memory is stored in MongoDB Atlas with Vector Search, scoped per team and role, expires, can be corrected or forgotten, and provably changes the next run. (Problem statement 2: *Memory You Can Govern*.)

## Where to look

| You need | Read |
|---|---|
| Your tasks, time boxes, checks | [docs/PLAN.md](docs/PLAN.md) |
| Tech stack, infrastructure diagram, core mechanisms | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| The three use-case flows, auth, memory, token rules | [docs/FLOWS.md](docs/FLOWS.md) |
| One credit card ad followed end to end, with sample JSON | [docs/WORKED_EXAMPLE.md](docs/WORKED_EXAMPLE.md) |
| Collection schemas, indexes, RBAC, API, service signatures | [docs/CONTRACTS.md](docs/CONTRACTS.md) |
| What to create in MongoDB, in what order, and the seed data | [docs/MONGODB_SETUP.md](docs/MONGODB_SETUP.md) |
| The backend as built: how to run it, what is verified, what data and the web app must match | [docs/BACKEND.md](docs/BACKEND.md) |
| Shared Atlas access, env vars, MCP setup | [docs/SETUP.md](docs/SETUP.md) |
| Demo script and rules checklist | [docs/DEMO.md](docs/DEMO.md) |

## How to pick up work

1. Ask your human which area they own: data, web app, or backend. One owner per area.
2. Read [docs/BACKEND.md](docs/BACKEND.md) for what exists and what your area must match, then [docs/PLAN.md](docs/PLAN.md) for the task checks.
3. Build to the shapes in [docs/CONTRACTS.md](docs/CONTRACTS.md). A task is done when its check passes.
4. Branch, PR, squash-merge (see Branching).

## Repo map

```
AGENTS.md  CLAUDE.md  README.md  .env.example  .gitignore
docs/
backend/
  requirements.in  requirements.txt (pinned, Python 3.12+)  pytest.ini
  app/main.py        FastAPI app, routers, error mapping
  app/models.py      shared shapes (docs/CONTRACTS.md section 6)
  app/core/          config.py  db.py  security.py  gate.py  llm.py  embeddings.py
  app/agent/         graph.py (route -> lane)  lanes.py (review, regenerate, memory update, ask)  prompts.py
  app/services/      compliance.py  compliance_rules.py  confidence.py   the review; the last two are pure
                     fundamentals.py  offers.py  memory.py  campaigns.py  media.py
                     mongo_sources.py  fixture_sources.py                where a review reads from
  app/routers/       auth  chat  compliance  campaigns  assets  fundamentals  memories  audit  runs
  scripts/           dry_run.py (review without the database)  smoke.py (live end to end)
                     build_seed.py (source data -> seed files)  load_db.py (seed files -> MongoDB)
  seed/              *.json, generated from northplay-demo-data/ by build_seed.py
  tests/             offline: rules, confidence, gate, services, whole API flow (on fixtures/tamarack)
northplay-demo-data/ the source data set: regulations, past ads, Slack export, strategy decks, 3 demo ads
frontend/            web app owner; not started in this repo yet
```

## Ownership

Edit only the files your area owns.

| Area | Owns |
|---|---|
| Data | `northplay-demo-data/**`, and the mapping choices in `backend/scripts/build_seed.py` |
| Web app | `frontend/**`, `docs/DEMO.md` |
| Backend | everything else under `backend/` |

**Shared files** change only in a small dedicated PR announced in team chat: `docs/CONTRACTS.md`, `backend/requirements.txt`, `.env.example`, `AGENTS.md`.

## Rules

1. **Stay in your lane.** If you need something from another stream, call its function as specified in `docs/CONTRACTS.md`. If the contract is not enough, stop and tell your human; do not edit another stream's files.
2. **Every state-changing action goes through `guarded()`** in `backend/app/core/gate.py`. No tool or router writes to the database or calls ElevenLabs directly.
3. **Identity comes from the JWT, never from model output.** Lanes receive `identity` and `run_id` as arguments from the router.
4. **Access scope lives in the query.** Team, role and status filters go in the `$vectorSearch` pre-filter or the `find` filter, never in a prompt instruction.
5. **Shared database.** Everyone works against the same Atlas cluster. Never drop collections or indexes. Never run an unfiltered delete or update. Schema, validator and index changes go only through `backend/scripts/setup_db.py`, which must stay idempotent. For destructive experiments set `MONGODB_DB=greenlight_<yourname>`.
6. **The repo is public. Never commit secrets.** No keys, passwords or connection strings in code, docs, tests, PR text or commit messages. `.env` is gitignored.
7. **Do not change the embedding model or its dimensions** (`voyage-3.5`, 1024). The vector indexes depend on it.
8. **Follow the token rules** in `docs/FLOWS.md`: deny before spending, one intent → one lane with no tool schemas sent to the model, filter before retrieving, summaries not documents, code before model, fast model for everything except the compliance verdict.
9. **No Streamlit, no new frameworks, no extra services.** The stack in `docs/ARCHITECTURE.md` is fixed.
10. **Original work only.** Do not paste code from other projects. Use only the fictional bank and card (Tamarack Bank, Tamarack Cashback Card) and stock ElevenLabs voices; no real institutions, card networks, people, voices or likenesses in seed data or demos.
11. **P0 before anything else.** Do not start a P1 or P2 task while a P0 task in your stream is open. Nothing new after the feature freeze at T+3:15.
12. **The model never sees a password.** UC4 changes are drafted by the agent and written by the web app calling the write endpoint with the password.
13. **Never invent offer terms.** Rates, fees, bonus amounts and conditions come only from the ad or the `offers` record. No offer record → stop and ask.
14. **Policy outranks memory.** Memory can add a team instruction or show a past verdict; it cannot waive a policy clause. Findings cite a policy key and version, the offer, or a memory id.
15. **Routing and release are code.** The route comes from the findings' materiality, never from a similarity score. Release re-checks the approval against current ad, policy and offer versions.
16. **Regeneration fails closed.** Review the corrected copy first; render audio or an image only from copy that has passed; one repair attempt at most; otherwise produce nothing and return the remaining findings.
17. **No image-generation model.** Regenerated images come from the brand template rendered in code, so rates and fine print are exact. Review always runs on text: transcribe audio and read images once, store the text on the ad, and reuse it.
18. **Build text first, then audio, then image.** Each must work end to end before the next is started.
19. **Confidence is computed in code.** Never ask the model for a confidence number. The judge labels each finding `clear`, `likely` or `unclear`; the score comes from the formula in `docs/CONTRACTS.md`. Drop any finding whose quote is not in the ad. Confidence may send a result to human review; it may never loosen a verdict or a route.

## Branching

Trunk-based. `main` must always start.

- One branch per task: `<stream>/<task-id>-<slug>`, for example `agent/b1-compliance-engine`, `web/d2-chat`, `audit/a3-fundamentals-stepup`, `memory/c3-memory-service`.
- Keep branches under about 45 minutes of work. Small PRs.
- Before pushing: `git pull --rebase origin main`.
- PR title: `[B1] Compliance engine`. Squash-merge it yourself once the task's check passes locally. There is no review gate in this event.
- Never force-push `main`. Never commit directly to `main` after Stream 0.
- Commit style: `feat(agent): …`, `fix(web): …`, `docs: …`.
- Merge conflict in a file you do not own: stop and tell your human.

## Definition of done

- The task's check in `docs/PLAN.md` passes.
- Backend and frontend still start locally.
- No secrets in the diff.
- PR squash-merged to `main`.

## Commands

```bash
# backend (Python 3.12 or later; the system python3 on macOS is too old)
cd backend && python3.13 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
pytest                           # 52 offline tests, no keys or database needed
python -m scripts.dry_run --suite   # live: every past ad against its recorded decision, no database needed
python -m scripts.dry_run --image ../northplay-demo-data/demo_ads/demo_03_play_smart_breaks.png --channel "Instagram (paid social)"
uvicorn app.main:app --reload --port 8000     # API on http://localhost:8000, docs at /docs
python -m scripts.smoke          # live end to end; run it against a scratch database, it writes test ads

# data: northplay-demo-data/ -> backend/seed/ -> MongoDB (refuses the shared `greenlight` without --shared)
python -m scripts.build_seed
python -m scripts.load_db --db greenlight --shared --password "$SEED_PASSWORD"
python -m scripts.load_db --db greenlight_scratch --password "$SEED_PASSWORD"   # a scratch copy for smoke
```

## Looking at the shared database from your agent

A read-only MongoDB MCP server is configured for Claude Code in `.mcp.json` and for Codex in `~/.codex/config.toml`; setup is in [docs/SETUP.md](docs/SETUP.md). Use it to inspect collections and indexes. It is read-only on purpose: writes happen through the app and the scripts.
