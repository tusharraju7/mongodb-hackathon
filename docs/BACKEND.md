# The backend as built

Everything under `backend/`. This page says what exists, what data it runs on, how to run it, what has and has not been verified, and what the data and web app owners need to know.

## Data set: NorthPlay

The backend now runs on `northplay-demo-data/`: NorthPlay, a fictional Ontario sportsbook. The shared `greenlight` database on the sandbox cluster holds it.

| Source | Becomes | Count |
|---|---|---|
| `regulations/regulations.json` | Policy clauses in `fundamentals` (`REG-01` … `REG-15`). Severity `blocker` → a finding that rejects; `major` → a finding that asks for changes | 15 |
| `historical_ads/` | Ads in `campaigns`, each with its image in GridFS and its recorded decision. Approved ones are `released`; rejected are `rejected`; approved-with-changes are `pending_review` | 15 |
| `historical_ads/` again | Past-verdict memories, one per ad | 15 |
| `slack/slack_export/` | One memory per channel per day, with a standing (below) | 26 |
| `strategy_decks/*.md` | One background memory per slide | 19 |
| All of the above, unchanged | `regulations`, `ad_decisions`, `slack_messages`, `strategy_docs`, so every memory can be traced to its source | |

`demo_ads/` is never loaded. Those three images are uploaded live.

**Standing of a Slack memory**, decided when the seed is built:

| Standing | Which threads | Effect of breaking it |
|---|---|---|
| Binding decision | Everything in `#legal-marketing`; decisions by the CEO, CMO or Senior Counsel elsewhere | Rejects the ad |
| Team guidance | Other threads that give an instruction (brand and style notes) | Asks for changes |
| Background | Everything else, and every deck slide | Never a finding on its own |

`#leadership` threads are visible to managers only. This classification is a rule of thumb in `scripts/build_seed.py`; Alton knows which six decisions were planted and may want to adjust it.

**Users** (password: `SEED_PASSWORD` in `.env`):

| Email | Role | Team |
|---|---|---|
| `ethan.cho@northplay.test` (Senior Counsel) | manager | ontario |
| `priya.nair@northplay.test` (CMO) | manager | ontario |
| `amira.haddad@northplay.test` (Creative Lead) | marketer | ontario |
| `kevin.tran@northplay.test` (Growth Marketing) | marketer | ontario |
| `jordan.blake@northplay.test` (Player Support; added for the demo) | sales | ontario |
| `manager.alberta@northplay.test`, `marketer.alberta@northplay.test` (added for the demo) | manager, marketer | alberta |

The Alberta team exists only to show that one team's memory does not reach another's.

To rebuild from the source folder:

```bash
python -m scripts.build_seed                 # northplay-demo-data/ -> backend/seed/*.json   (--read-images re-reads the 15 ad images)
python -m scripts.load_db --db greenlight --shared --password "$SEED_PASSWORD"
```

## How a chat turn runs

An explicit graph with two steps, not a free tool-calling agent:

1. **Route.** A file or pasted ad copy is a review, with no model call. Otherwise the fast model classifies the message as review, regenerate, memory update, ask, approve/release, or other.
2. **Act.** Code checks the role against `policies` for the action that intent needs. A role that lacks it gets a fixed refusal, a `deny` on the ledger, and no further model call. Otherwise the lane runs, each step a separate gated action.

No tool schema is ever sent to a model. The model is called for: routing, claim extraction, image reading, the verdict, one copy repair, drafting a memory change, and answering a question.

## How a review decides

1. **Read.** An image is read once (all its text, plus notes on what is shown and whether the disclaimer is easy to read); audio is transcribed.
2. **Claims.** The fast model lists the ad's claims by type (inducement, free or risk-free, odds or certainty, endorsement, and so on).
3. **Checks in code.** The required disclaimer (a responsible gambling message and 19+), and whether it is legible.
4. **Clauses.** Every clause that applies to the ad's product and region is shown to the judge; with 15 there is no need to pick.
5. **Memory.** Searched once for the whole ad and once per claim, so a single name such as "Jake Moreau" finds the decision about it. Each standing has its own share of the result (5 binding, 2 guidance, 3 past verdicts, 2 background). A manager's team-wide instruction entered through the product is always in view, without relying on search.
6. **Verdict.** The main model returns findings, each citing a clause or a memory, with the quote, reasoning and certainty. Policy is the floor; binding decisions add to it and the most recent wins; background never excuses a finding.
7. **In code.** Findings that quote words not in the ad are dropped. Confidence is computed. A finding labelled unclear cannot reject an ad on its own; it sends it to a person. The decision is `approved`, `approved_with_changes` or `rejected`.

## Verified

| Check | Result |
|---|---|
| Offline tests (`pytest`) | 52 pass. They run on the earlier fictional-bank fixtures in `tests/fixtures/`, which exercise every code path including offer records |
| The 15 past ads (`scripts/dry_run.py --suite`), each reviewed without the memory of its own decision | 14 match the recorded decision. `NP-H05` comes back stricter (below) |
| The 3 demo ads, uploaded as images through the API | Demo 1 approved. Demo 2 rejected on `REG-12`, `REG-13` and a Slack decision. Demo 3 rejected on the Jake Moreau decision alone, with no regulation cited; replayed without memory it is not rejected |
| Live end to end on Atlas (`scripts/smoke.py`, on a scratch copy) | 38 of 39. The one failure, a new team instruction not taking effect on the very next review, was fixed and re-checked live |
| Regenerate | Demo 3 is regenerated as a new banner without the athlete and passes the same review |

**`NP-H05`** (the opted-in bonus email, recorded as approved) is rejected today on two points: the creative shows no unsubscribe option (`REG-15`), and it says "any NFL game" after Legal's 20 October message that NorthPlay holds no NFL marks. Whether that is right is a call for Alton, who holds the answer keys.

**Not verified:** the three demo ads against Alton's answer keys beyond what the README states; how traces look in LangSmith; that two users' same-named conversations stay separate (it follows from how thread ids are built, but nothing tests it).

**Not built:** reuse of a stored verdict for an unchanged ad, the "review our policies for gaps" request, and turning reject feedback into a memory.

## Measured

| | |
|---|---|
| One image review | About 9 to 14 s and 10,000 to 12,000 input tokens (image reading 2,000 to 3,500, claims 2,100, verdict 6,000 to 8,000) |
| Verdict effort | `LLM_EFFORT=low`. Raising it to `medium` made reviews about three times slower with the same findings on the ads tried |

## Things that will bite

- **Voyage rate limit.** An account without a payment method allows 3 requests and 10,000 tokens a minute. A review makes 2 embedding requests, so the app waits and retries when limited, and a live demo can stall. Adding a payment method in the Voyage dashboard lifts it; the free token allowance still applies.
- **"Image analyzers" are on the banned list.** All three demo ads are images. Keep the pitch on the governed decision (who decided, on which rule or Slack decision, and what changed), not on reading the image.
- **LangSmith.** Set `LANGSMITH_PROJECT`, or the `LANGSMITH_AGENT_ID` / `LANGSMITH_AGENT_ENVIRONMENT` pair, never both. With both set LangSmith refuses to trace.
- **Python.** 3.12 or later. On macOS the system `python3` is 3.9; use `python3.13`.
- **Other docs.** `FLOWS.md`, `WORKED_EXAMPLE.md`, `CONTRACTS.md` section 3 and `DEMO.md` still use the earlier fictional-bank example. The mechanisms they describe are the ones running; the names and rules in them are not NorthPlay's.

## For the data owner

- The mapping above lives in `scripts/build_seed.py`; the loader is `scripts/load_db.py`. Both can be run again safely.
- Regulations are stored in `fundamentals`, not `policies`. In this backend `policies` holds the role permissions.
- Text embedded for a clause is `"{title}. {rule, checks and fix}"`; for an ad, `"{description} {summary}"`; for a memory, its text. Voyage `voyage-3.5`, 1024 dimensions.
- Things worth a look: which Slack threads count as binding; whether past approved-with-changes ads should sit as `pending_review`; and the `NP-H05` result.

## For the web app owner

Base URL `http://localhost:8000`; interactive docs at `/docs`. Send `Authorization: Bearer <token>` on everything but `/auth/login`.

| Topic | What the backend does |
|---|---|
| Reviewing an uploaded ad | `POST /assets` (multipart, image or audio) → `{ file_id, type }`, then `POST /chat` with `{ thread_id, run_id, file_id, ad: { name, channel } }`. `channel` is free text, for example "Instagram (paid social)" or "Email (opted-in players)"; some rules depend on it. Product and region default to NorthPlay's; there is no offer to pick |
| Reviewing pasted copy | `POST /chat` with `ad: { text, name, channel }` |
| Reviewing a library ad again | `ad: { campaign_id }` |
| Report | `decision` is `approved`, `approved_with_changes` or `rejected`; `verdict` is the same thing as `pass`, `needs_changes`, `blocked`. Each finding has either `fundamental_key` (a regulation) or `memory_id` with `evidence.memory_text` (the Slack decision it rests on) |
| Replay without memory | Same request with `use_memory: false`, or `POST /compliance/check { campaign_id, use_memory: false }` |
| Memory list | `GET /memories` items carry `authority` (`binding`, `guidance`, `precedent`, `background`) and `source` (`{ type: "slack", channel, date, authors }`, `strategy_deck`, or `ad_decision`) |
| Errors | `{ "error": "<code>", "message": "..." }`. Codes: `denied` 403, `step_up_failed` 401, `stale_approval` 409 (with `changes`), `not_approvable` 409, `stopped` 409, `not_found` 404, `unsupported_media` 415, `embedding_rate_limited` 429, `model_refused` / `model_failed` 502. Login and token failures use `{ "detail": "..." }` with 401 |
| Approve | Only an ad that is pending review and approved by the review can be approved by a manager. Anything else returns 409 `not_approvable`: regenerate first |
| `memory_change` card | `{ target: "fundamental" or "memory", id, key?, kind?, scope?, before, after, action: "create" / "correct" / "forget", status: "proposed", requires_password, version? }`. To apply: `PUT /fundamentals/{id}`, `POST /memories`, `PATCH /memories/{id}` or `DELETE /memories/{id}`, with `password` and `reason` when `requires_password` is true |
| Denied or stopped in chat | `/chat` returns 200 with `status: "denied"` or `"stopped"` and a fixed reply; the refusal is on the ledger. Direct endpoints return 403 or 409 |
| `/campaigns/{id}/regenerate` | Returns `{ status, campaign, report, attempts, reply, run_id, tokens }`. A regenerated image is a new NorthPlay-styled banner carrying the corrected copy, not an edit of the original artwork |
| Run id on writes | Every write endpoint accepts an optional `run_id` and returns the one it used, for `/runs/{id}/rollback` and `/audit/stream?run_id=`. `DELETE /memories/{id}` returns it in the `X-Run-Id` header |
| Ad card | `asset` is `{ type, url }` or null; fetch `url` with `?token=<jwt>` for `<img>` and `<audio>`. `text` is always present and is what was reviewed |
