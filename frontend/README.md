# Greenlight React

A real React + TypeScript frontend in the repository's Next.js structure for the MongoDB hackathon agent. The primary interface is a conversation with a policy-first ad review card. There is no approval dashboard. User and Lawyer views are explicitly labeled.

## Open or share the demo

Open `share/greenlight-demo.html` in a browser. Send that **one file** to a colleague. React, CSS, icons and all three demo images are embedded; no installation, internet connection, backend credentials or AI usage is needed. It starts in demo mode. Demo actions and findings are simulated, and sample-ad history stays in the current browser. Sharing the file does not export your browser's history.

For a public demo URL, host the contents of `dist/` on a static host, or serve the single HTML file. This package does not publish a site automatically. It contains no API keys, database credentials or login tokens. Public **live** AI access is a separate deployment decision; verify server-side quotas and spending controls first.

## Demo sign-in

| Workspace | Username | Password |
| --- | --- | --- |
| User | `demo.user` | `ReviewDemo!26` |
| Lawyer | `demo.lawyer` | `LegalDemo!26` |

These are public fake credentials, never real secrets. Login rejects invalid passwords and mismatched workspace selection. Sign out to change accounts; there is no in-session role switch. Credentials and demo identity are not saved in local storage. Refresh requires sign-in again; sample review history remains in this browser.

This is client-side demo login validation, **not secure authentication**. A standalone HTML file cannot protect data or enforce authorization against browser tampering. The live FastAPI service must authenticate and authorize all real actions when integration resumes. Backend integration is currently on hold; the adapter below targets an older contract and must be reconciled before use.

Local image copies of all three ads are in `demo-ads/`. New conversations start with a minimal message/upload box; only assessed samples show policy cards. Uploaded files are preview-only in demo mode.

## Develop and test

Use Node.js 22 or later (current LTS recommended).

```powershell
cd "C:\Users\rulan\Desktop\MongoDB Hackathon\frontend"
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`. Next.js reloads the development view when source files change.

```powershell
npm test
npm run build
npm run preview
```

`build` produces the Next.js static export in `out/`, then bundles the same React components into `dist/index.html` and `share/greenlight-demo.html`. `preview` serves the portable production build at the same local URL. Stop the dev server before starting preview on port 3000. No Node server is needed after static deployment.

## Connected backend setup

The current branch includes `main` at d6ca6c6 and `agent/round-two` at 9949bca. The preserved Claude baseline is `docs/RESULTS.md`: prompt version 2026-11-14.3, 14/15 historical outcomes matched, and all three demo outcomes matched.

1. Put `OPENAI_API_KEY` and the existing NorthPlay account password (`SEED_PASSWORD`) in the ignored repo-root `.env`. JWT signing is configured locally. Never commit these values.
2. Configure `LLM_MODEL=openai:gpt-5.4-mini`, `LLM_FAST_MODEL=openai:gpt-5.4-mini`, `LLM_EFFORT=low`, `LLM_FAST_EFFORT=none`. The adapter also retains Anthropic support.
3. From `backend/`, run `.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. Windows dependency installation skips uvloop.
4. Open the React preview, choose **Connect backend**, and use `http://127.0.0.1:8000`. User: `amira.haddad@northplay.test`. Lawyer: `ethan.cho@northplay.test`. Both require their existing database passwords; fake offline demo credentials do not work here.
5. Choose Ontario and an actual channel (for example Instagram paid social), upload an image or paste copy, then **Review ad**. Submission rechecks and files the project. The library is shared by team; the server enforces roles and only permits approval of passing, pending projects.
6. Project chat IDs persist across navigation. `GET /chat/{thread_id}` restores the latest six turns, scoped by the authenticated user. Model confidence remains evidence confidence, never a fabricated risk score. Live coordinates/readiness are shown only if returned by the backend.

In VS Code, use **Terminal → Run Task** for Backend: run, Backend: tests, or Services: check. Stop a running backend before starting another on port 8000. Services: check makes one tiny Voyage request and prints configuration presence and MongoDB counts; it cannot report remaining billing credits.

To compare using the same fixture data and prompts, run from `backend/`:

```powershell
.venv/Scripts/python -m scripts.dry_run --suite --report ../docs/RESULTS_OPENAI.md
```

This incurs model and Voyage usage. Do not overwrite `docs/RESULTS.md`, the Claude baseline. It runs against local seed fixtures rather than modifying the shared campaign database. Generated OpenAI results are not available until credentials are supplied and this run succeeds.

## How the pieces connect

```text
React browser UI -- HTTP(S), JSON + multipart --> Python/FastAPI
                                                  |-- MongoDB: ads, policy, memory, history
                                                  |-- Voyage AI: embeddings / retrieval
                                                  `-- LLM + vision: extraction and assessment
```

Node.js runs the frontend toolchain. NestJS and an extra Node API server are unnecessary. The browser never calls MongoDB, Voyage or the model provider directly.

| UI action | Backend route |
| --- | --- |
| Login | `POST /auth/login` with email/password |
| Available offers | `GET /offers` |
| Image upload | `POST /assets` multipart field `file` |
| Assess without filing | `POST /compliance/check` with `save: false` |
| Submit | `POST /compliance/check` with `save: true` |
| Follow-up conversation | `POST /chat` with stable `thread_id` within the active conversation |
| Stored reviews / full record | `GET /campaigns`, `GET /campaigns/{id}` |
| Protected image | `GET /assets/{file_id}` with bearer header, displayed as a local blob URL |
| Lawyer decision | `POST /campaigns/{id}/approve` or `/reject` with feedback |
| Stop between agent steps | `POST /runs/{run_id}/stop` |

The bearer token stays in React memory and is cleared on sign-out/reload. Protected image URLs never contain the token. Live results are not stored in localStorage. The frontend restores the latest six backend chat turns per project and authenticated user.

## Demo versus live behavior

- **Demo:** Hockey Night Live has readiness 92; Big game bonus has 75 and two red rectangles. Play Smart — Breaks has 64: it passes sample regulatory checks but is blocked by the October 30 internal legal guidance terminating Jake Moreau’s rights; its name and quote are highlighted. These are fixtures, not AI results. Below 80, explicit acknowledgement enables **Submit anyway**. Pending reviews can be examined in Lawyer view; passing ads can be approved, blocked ads can be rejected with feedback.
- **Live:** Existing report confidence means evidence strength. It is never converted into risk/readiness. Missing readiness and coordinate fields stay absent. See `BACKEND_HANDOFF.md` for the proposed optional output fields.
- **Uploads:** New image/PDF/video attachments can be selected locally in demo mode, but receive no invented assessment. PDF/video are attachments only, with no analysis or video playback. Live upload is limited here to PNG/JPEG/WebP/GIF up to 20 MB. The backend requires PDF/video processing work before those formats can be analysed.
- **Policies:** NorthPlay sportsbook rules are loaded in the shared MongoDB database. The old credit-card dataset is used only by offline tests.
- **History:** Shared project versions and decisions; separate per-user chat with six-turn server retention. Older messages are not retained by the current graph.
- **Spending:** The inspected branch records token usage, limits per-call output and handles Voyage rate-limit errors. No application-wide hard cost cap, per-user quota, or remaining-credit cutoff was verified. Keep live accounts restricted until server-side controls are committed and tested. The offline demo makes no AI calls.

## Source map

- `src/App.tsx`: roles, conversation, uploads, submission, review decisions and history.
- `src/ReviewCard.tsx`: policy evidence first, image annotations, then improvements.
- `src/api.ts`: FastAPI transport; replace only this adapter if routes change.
- `src/domain.ts`: threshold, authorization display rules and annotation validation.
- `src/demo.ts`: clearly labeled sample reports and coordinates.
- `tests/`: meaningful boundary checks and mocked HTTP contract tests.
- `scripts/build.mjs`: reproducible bundle and single-HTML packaging.

Demo image provenance: `northplay-demo-data/demo_ads/demo_01_hockey_night_live.png` and `demo_02_big_game_bonus.png`, and `demo_03_play_smart_breaks.png` at `main` commit `1a4cd407c78321a49384b9b1282055339aa6a149`. The policy paraphrases are fictional demo content, not a live legal determination.
