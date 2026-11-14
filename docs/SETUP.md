# Setup

## 1. The shared Atlas Sandbox

Hackathon rule: finalists must build on the MongoDB Atlas Sandbox provided for the event. The whole team uses **one** cluster and **one** database.

| | |
|---|---|
| Atlas project | the repo owner's hackathon *Sandbox Project* |
| Cluster | `Cluster0` — M10 dedicated, MongoDB 9.0, AWS us-west-1 |
| Host | shared privately with the connection string (this repo is public) |
| Database | `greenlight` |

Before kickoff the repo owner confirms that this project was created from the hackathon email link.

### Repo owner, once (Stream 0, task S0.1)

1. **Database user for the app and the team.** Atlas → Database Access → Add New Database User. Username `greenlight_app`, a generated password, built-in role *Read and write to any database* restricted to this cluster, or a custom role with `readWrite` on `greenlight`. Do not share the existing admin user.
2. **Network access.** Atlas → Network Access → add each teammate's IP (each person runs `curl ifconfig.me`). If the venue network keeps changing addresses, add a temporary `0.0.0.0/0` entry with an expiry and delete it after the demo.
3. **Share the connection string privately** (team chat DM or a password manager), never in the repo, an issue or a PR:
   `mongodb+srv://greenlight_app:<password>@<cluster-host>/?retryWrites=true&w=majority`
4. Optional: Atlas → Project Access → invite teammates as *Project Data Access Read/Write* so they can use Data Explorer and see the search indexes.

### Working together in one database

- Everyone points at `greenlight`. Seed data is shared, so the app looks the same on every laptop.
- Collections, validators and indexes are created only by `backend/scripts/setup_db.py`. It is idempotent; run it again after pulling a change to it.
- Never drop collections or indexes, and never run an unfiltered delete or update.
- For a destructive experiment, set `MONGODB_DB=greenlight_<yourname>` locally and run `setup_db` + `seed` there.
- Audio lives in GridFS in the same database, so there is no shared file storage to set up.

## 2. Keys each person needs

| Key | Where from | Used by |
|---|---|---|
| MongoDB connection string | repo owner, privately | everyone |
| LLM key (Anthropic or OpenAI) | your own or the team's | streams B, C; anyone running the backend |
| Voyage AI key | Atlas (AI model API keys) or the Voyage dashboard; one shared team key is fine | streams A, B, C |
| ElevenLabs key | hackathon credits; one shared team key | stream C; anyone reviewing audio ads or running the seed script |

## 3. Environment variables

Copy `.env.example` to `.env` in the repo root. `.env` is gitignored.

```
MONGODB_URI=                 # shared connection string
MONGODB_DB=greenlight

LLM_MODEL=anthropic:claude-opus-5-5        # compliance verdict
LLM_FAST_MODEL=anthropic:claude-haiku-5-5  # router, Q&A, extraction, drafting
ANTHROPIC_API_KEY=
OPENAI_API_KEY=              # only if you set the two models to openai:<model>

VOYAGE_API_KEY=
VOYAGE_MODEL=voyage-3.5      # do not change: indexes are 1024-dimensional

ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=         # stock voice used by the seed script for the sample ads

JWT_SECRET=                  # same value for the whole team so tokens work across laptops
SEED_PASSWORD=               # password given to all seeded demo users

NEXT_PUBLIC_API_URL=http://localhost:8000

# optional tracing
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
```

## 4. Seeded demo users

Created by `scripts/seed.py`, all with `SEED_PASSWORD`.

| Email | Role | Team |
|---|---|---|
| `manager.national@solstice.test` | manager | national |
| `marketer.national@solstice.test` | marketer | national |
| `sales.national@solstice.test` | sales | national |
| `manager.quebec@solstice.test` | manager | quebec |
| `marketer.quebec@solstice.test` | marketer | quebec |
| `sales.quebec@solstice.test` | sales | quebec |

## 5. Let your coding agent see the database (MongoDB MCP, read-only)

**Claude Code** — `.mcp.json` in the repo root (created in Stream 0). It reads the connection string from your shell environment, so nothing secret is committed. Export `MONGODB_URI` before starting Claude Code.

```json
{
  "mcpServers": {
    "mongodb": {
      "command": "npx",
      "args": ["-y", "mongodb-mcp-server@latest", "--readOnly"],
      "env": { "MDB_MCP_CONNECTION_STRING": "${MONGODB_URI}" }
    }
  }
}
```

**Codex** — add to `~/.codex/config.toml` on your machine (outside the repo):

```toml
[mcp_servers.mongodb]
command = "npx"
args = ["-y", "mongodb-mcp-server@latest", "--readOnly"]
env = { MDB_MCP_CONNECTION_STRING = "<your connection string>" }
```

Other agents: any MCP client can run the same command. Keep `--readOnly`.

## 6. Run locally (after Stream 0)

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev     # http://localhost:3000
```

## 7. Before submission

- The repo is public.
- `git log -p | grep -iE "mongodb\+srv://[^<]|sk-|api_key=."` finds nothing real.
- The temporary `0.0.0.0/0` access-list entry, if used, is removed after judging.
