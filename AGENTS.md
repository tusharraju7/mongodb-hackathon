# AGENTS.md — guidance for every coding agent in this repo

This file is the single source of guidance for Claude Code, Codex, and any other agent. `CLAUDE.md` only imports it. Read this file fully, then the doc for your task.

## What we are building

**Greenlight**: a governed marketing agent for an organisation, built in a 4-hour hackathon by a team of 4.

- It reviews existing ad creative, creates new creative from a prompt (script + ElevenLabs voiceover), compares campaigns, answers questions about ads, and lets the marketing manager update what the agent remembers.
- Every action is tied to an identity, checked against policy **before** it runs, and recorded in a ledger. Runs can be stopped and rolled back. (Problem statement 1: *Agents You Can Audit*.)
- Memory is stored in MongoDB Atlas with Vector Search, scoped per team and role, expires, can be corrected or forgotten, and provably changes the next run. (Problem statement 2: *Memory You Can Govern*.)

## Where to look

| You need | Read |
|---|---|
| Your tasks, time boxes, checks | [docs/PLAN.md](docs/PLAN.md) |
| Tech stack, infrastructure diagram, core mechanisms | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| The five use-case flows, auth, memory, token rules | [docs/FLOWS.md](docs/FLOWS.md) |
| Collection schemas, indexes, RBAC, API, service signatures | [docs/CONTRACTS.md](docs/CONTRACTS.md) |
| Shared Atlas access, env vars, MCP setup | [docs/SETUP.md](docs/SETUP.md) |
| Demo script and rules checklist | [docs/DEMO.md](docs/DEMO.md) |

## How to pick up work

1. Ask your human which stream they own (0, A, B, C or D). One person per stream.
2. Open [docs/PLAN.md](docs/PLAN.md), find the first unfinished task in that stream, and do only that task.
3. Build to the shapes in [docs/CONTRACTS.md](docs/CONTRACTS.md). Each task has a check; the task is done when the check passes.
4. Branch, PR, squash-merge (see Branching). Then take the next task.

## Repo map

The repo currently holds documentation only. Stream 0 creates this layout; do not invent a different one.

```
AGENTS.md  CLAUDE.md  README.md  .env.example  .gitignore  .mcp.json
docs/
backend/
  requirements.txt
  app/main.py
  app/core/      config.py  db.py  security.py  gate.py  llm.py  embeddings.py
  app/routers/   auth.py  chat.py  compliance.py  campaigns.py  assets.py
                 fundamentals.py  memories.py  audit.py  runs.py
  app/agent/     graph.py  tools.py  prompts.py
  app/services/  compliance.py  generation.py  campaigns.py  memory.py  fundamentals.py
  scripts/       setup_db.py  seed.py  smoke.py
  seed/          *.json
frontend/        Next.js app: app/{login,chat,library,fundamentals,memory,audit}/page.tsx
                 lib/api.ts  lib/types.ts
```

## Ownership

Edit only the files your stream owns.

| Stream | Scope | Owns |
|---|---|---|
| 0 | Bootstrap | Initial scaffold of everything above, then hands off |
| A | Identity, policy, audit | `backend/app/core/{security,gate}.py`, `backend/app/routers/{auth,fundamentals,audit,runs}.py`, `backend/app/services/fundamentals.py`, `backend/scripts/setup_db.py` |
| B | Agent and compliance | `backend/app/agent/*`, `backend/app/services/compliance.py`, `backend/app/routers/{chat,compliance}.py`, `backend/app/core/llm.py` |
| C | Memory, retrieval, generation | `backend/app/services/{memory,campaigns,generation}.py`, `backend/app/routers/{campaigns,assets,memories}.py`, `backend/app/core/embeddings.py`, `backend/scripts/seed.py`, `backend/seed/*` |
| D | Web app | `frontend/**`, `docs/DEMO.md` |

**Shared files** change only in a tiny dedicated PR announced in team chat: `docs/CONTRACTS.md`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/main.py`, `backend/requirements.txt`, `.env.example`, `AGENTS.md`.

## Rules

1. **Stay in your lane.** If you need something from another stream, call its function as specified in `docs/CONTRACTS.md`. If the contract is not enough, stop and tell your human; do not edit another stream's files.
2. **Every state-changing action goes through `guarded()`** in `backend/app/core/gate.py`. No tool or router writes to the database or calls ElevenLabs directly.
3. **Identity comes from the JWT, never from model output.** Tools receive `identity` and `run_id` by closure.
4. **Access scope lives in the query.** Team, role and status filters go in the `$vectorSearch` pre-filter or the `find` filter, never in a prompt instruction.
5. **Shared database.** Everyone works against the same Atlas cluster. Never drop collections or indexes. Never run an unfiltered delete or update. Schema, validator and index changes go only through `backend/scripts/setup_db.py`, which must stay idempotent. For destructive experiments set `MONGODB_DB=greenlight_<yourname>`.
6. **The repo is public. Never commit secrets.** No keys, passwords or connection strings in code, docs, tests, PR text or commit messages. `.env` is gitignored.
7. **Do not change the embedding model or its dimensions** (`voyage-3.5`, 1024). The vector indexes depend on it.
8. **Follow the token rules** in `docs/FLOWS.md`: deny before spending, one intent → one small tool set, filter before retrieving, summaries not documents, code before model, fast model unless writing a script.
9. **No Streamlit, no new frameworks, no extra services.** The stack in `docs/ARCHITECTURE.md` is fixed.
10. **Original work only.** Do not paste code from other projects. Use only the fictional brand (Solstice Coffee Co.) and stock ElevenLabs voices; no real people's names, voices or likenesses in seed data or demos.
11. **P0 before anything else.** Do not start a P1 or P2 task while a P0 task in your stream is open. Nothing new after the feature freeze at T+3:15.

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

## Commands (available after Stream 0)

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
python -m scripts.setup_db      # collections, validators, indexes (idempotent)
python -m scripts.seed          # users, policies, fundamentals, campaigns, memories
python -m scripts.smoke         # end-to-end assertions against the shared cluster

# frontend
cd frontend && npm install && npm run dev      # http://localhost:3000
```

## Looking at the shared database from your agent

A read-only MongoDB MCP server is configured for Claude Code in `.mcp.json` and for Codex in `~/.codex/config.toml`; setup is in [docs/SETUP.md](docs/SETUP.md). Use it to inspect collections and indexes. It is read-only on purpose: writes happen through the app and the scripts.
