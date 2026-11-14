# Live local Greenlight app

Open http://127.0.0.1:3000 in Chrome. The default is Connect backend, using the same-origin `/api` proxy to FastAPI on port 8000. Both processes bind to loopback only.

The ignored `.env` selects the isolated Atlas database `greenlight_rulan_live`. It contains the NorthPlay seed data and separate test accounts. The shared `greenlight` database and its existing account passwords are unchanged. Test account passwords are held in the local ignored `.env` as SEED_PASSWORD; never commit them.

- User: `amira.haddad@northplay.test`
- Lawyer: `ethan.cho@northplay.test`

Sign in, choose Use Hockey ad / Use Bonus ad / Use Play Smart ad (or attach your own image), then click Review ad. These controls upload the actual image through `/assets` and run `/compliance/check`; they do not load the saved comparison reports. Submit files the assessed project in Atlas. The lawyer can open it under Saved backend reviews. Approval and rejection use authenticated server routes.

For local startup, run `npm run preview` in frontend after `npm run build`, and `.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` in backend. The active local backend uses the Claude API and Voyage retrieval; the Codex CLI adapter remains available as an optional provider. `npm run dev` also proxies `/api` to FastAPI.

The browser API wrapper calls fetch through a function, avoiding the illegal receiver binding that prevented live requests. A regression test covers this. Saved demos remain an optional separate mode; they are not the live application.

Local model profile: assessments use `anthropic:claude-opus-5-5`; smaller steps use `anthropic:claude-haiku-5-5`, both at low effort. Configure `ANTHROPIC_API_KEY` in the ignored local `.env` and restart FastAPI after changing providers. Historical Codex reports remain comparison records.
