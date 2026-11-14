# Local Codex backend

This development adapter calls the signed-in `codex exec` CLI, then validates its JSON against the existing Pydantic schemas. The Python agent, LangChain/LangGraph orchestration, policy rules, retrieval, confidence calculation and permissions remain in place. This is a provider change, not a framework migration.

## Local setup

Install/sign into the official Codex CLI with `codex login`. Keep credentials in its normal credential store. In the ignored root `.env`, set:

```dotenv
LLM_MODEL=codex:gpt-5.6-sol
LLM_FAST_MODEL=codex:gpt-5.6-luna
LLM_EFFORT=low
LLM_FAST_EFFORT=low
```

These model names were verified in the installed CLI catalog and successfully used for this run. If Codex is not on PATH, set `CODEX_CLI_PATH` to the executable. Restart FastAPI after changing settings. Run it locally on `127.0.0.1:8000`; the frontend is on `127.0.0.1:3000`.

The subprocess uses a temporary working directory, read-only sandbox, ignored user configuration, disabled shell/browser/apps/hooks, no web search, a 180-second per-call timeout and one in-flight CLI call per backend process. Backend credentials are omitted from its environment. Authentication uses the CLI's saved ChatGPT login; it does not extract tokens or use OPENAI_API_KEY. Codex plan limits still apply, and retrieval still uses Voyage. This adapter is for local development, not a multi-user public deployment.

## Reproduce the saved comparison

From `backend`, run `.venv/Scripts/python -m scripts.codex_demos`. This uses the same review pipeline with scoped fixture sources, actual image reading and Voyage retrieval, without writing to Atlas. It saves:

- `docs/RESULTS_CODEX.md`: decision comparison with the preserved Claude baseline.
- `docs/results/codex-demos.json`: full readings, findings, provenance, model names, times and token usage.
- `frontend/src/codex-results.json`: the same results for the saved-demo UI.

From `frontend`, run `npm run build` and `npm run preview`. Choose **Saved demos** and a prefilled demo account. Each project shows the actual saved Codex report beside the original image, with Claude's baseline decision. Follow-up chat and approve/reject interactions in this mode are local simulations; they do not call the LLM or write to Atlas. **Connect backend** uses the authenticated FastAPI routes and requires an existing NorthPlay account password; demo credentials do not authenticate there.

Saved assessments contain no readiness/risk score or image-region coordinates, so the frontend does not substitute illustrative values. Evidence confidence is shown separately. Human workflow status remains distinct from the model's recommendation.

## Observed comparison

All three decisions matched Claude: approved, rejected, rejected. The bonus ad's Codex findings cite REG-12, REG-13 and the November 4 Slack decision; Claude additionally cited REG-06. Play Smart is rejected on the October 30 Jake Moreau decision alone. The no-memory ablation was not rerun for Codex.

CLI runs took 52.43, 63.15 and 59.57 seconds, versus the baseline's 12, 18 and 14 seconds. Token counts include CLI context overhead, so they are not a direct prompt-only or dollar-cost comparison. This route is convenient for local testing but is slower than the recorded Claude API runs.

Validation: 61 backend tests, 20 frontend tests and production build passed. Browser verification confirmed all three saved reports and their source labels. `/health` confirmed the configured CLI models and reachable MongoDB. Live authenticated browser upload was not tested because the shared account password is not configured locally.

Official CLI reference: https://learn.chatgpt.com/docs/non-interactive-mode
