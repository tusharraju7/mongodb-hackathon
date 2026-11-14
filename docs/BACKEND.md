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

## What an agent may do, and what is recorded (round two)

The reasoning behind this section is in [DESIGN_NOTES.md](DESIGN_NOTES.md).

**Before every step**, `guarded()` in `core/gate.py` calls `authorize()`, which asks five questions in order. The first that fails decides, and the refusal goes on the ledger naming that check, before anything runs.

| Check | Refuses when | Decided by data in |
|---|---|---|
| `identity` | The user was disabled, changed role or team, or had their access version raised since signing in | `users`, re-read at every step |
| `role` | The role does not hold the action | `policies` |
| `initiator` | The agent attempts something only a person may do: approve, release, edit a policy, forget a memory, stop or roll back a run, change a user's access | `action_rules` |
| `state` | The target is another team's, or in the wrong state (not passed, not approved, approval stale) | `action_rules` and the target |
| `limits` | The run has used its budget: 60 steps, 20 model calls, 200,000 tokens, 8 paid external calls | `action_rules._limits` |

A lane declares its steps up front; all are checked before the first runs, and the plan is stored on the run (`runs.plan`). Each step is checked again when it executes.

**The ledger** is insert-only and chained: each event has `seq`, `prev_hash` and `hash`, so an edited, removed or inserted event is detectable. Beside decisions and outcomes it records each model call (model, prompt version, tokens, latency, hashes of prompt and answer; never the text), each retrieval (the scope filters and what came back), each finding (what it rests on and how its confidence was made up), each conflict between sources, and crash recovery.

**If a run crashes**, every completed step has its result stored under a fixed key. Resuming reuses those results and calls no model for them again. A step that was in flight is checked for the effect it may have had, so nothing is filed or remembered twice. A run that failed on an outside service (a rate limit, a model error) resumes the same way.

**Memory changes with use.** A manager's decision on a reviewed ad strengthens or weakens the memories that review used; an override is stored as a stronger memory; past verdicts and background fade when unused, and binding decisions never do. The lesion test proves which memory changed a verdict by repeating the review without it.

**Video** goes through the same flow: speech is transcribed, six frames are read for on-screen text, and the review runs on that. Nothing is marked on a video and a video is not regenerated.

## The agent (`POST /agent`)

Everything else in the backend is a fixed flow: code picks the steps, the model fills them in. `POST /agent` is the one place the model picks its own next step. It is given a goal and eight tools: find an ad, review an ad, review pasted copy, read a regulation, search memory, regenerate (update) an ad, approve, release. It calls them one at a time until it replies, for at most 8 turns.

- **Each turn is a gated step** (`agent.run`): the user is re-read, the run budget is checked and a stop request takes effect before the model is asked.
- **Each tool is an existing lane or service, run as the agent**, so the five checks apply to every call. Approve and release are offered on purpose: the gate refuses them (`decided_by: initiator`), the refusal goes back to the model as the tool's result, and the model has to say so.
- **When the review calls for changes, the agent updates the ad.** `regenerate_ad` files the next version only after the corrected copy has passed the same review, renders the banner in code, and with `voice: true` records a voice-over of the passing copy with an ElevenLabs stock voice. An ad that passes as it is is left alone.
- **Verdicts are still computed in code** inside `review_ad`; the model reports them.
- Each tool call is a `tool_call` event on the ledger; `/runs/{id}/trace`, `/audit/verify` and `/runs/{id}/rollback` work on agent runs as on any other. Agent runs are not resumable after a crash (the lanes inside them keep their own checkpoints).

Request `{ goal, campaign_id?, run_id?, max_turns? }`. Response `{ reply, status, steps: [{ turn, tool, input, status, summary }], turns, campaign, report, voiceover_url, run_id, tokens }`. `status` is `completed`, `denied`, `stopped` or `incomplete` (turn cap reached). `AGENT_MODEL=main` runs the loop on the verdict model instead of the fast one.

`POST /campaigns/{id}/regenerate` also accepts `voice: true`. The ad card gains `voiceover: { url, mime }`.

## Verified

| Check | Result |
|---|---|
| Offline tests (`pytest`) | 81 pass: the original 52, 25 for round two (`tests/test_round_two.py`) and 4 for the agent (`tests/test_agent.py`). They run on the earlier fictional-bank fixtures in `tests/fixtures/`, which exercise every code path including offer records |
| The 15 past ads (`scripts/dry_run.py --suite`), each reviewed without the memory of its own decision | 14 match the recorded decision. `NP-H05` comes back stricter (below) |
| The 3 demo ads, uploaded as images through the API | Demo 1 approved. Demo 2 rejected on `REG-12`, `REG-13` and a Slack decision. Demo 3 rejected on the Jake Moreau decision alone, with no regulation cited; replayed without memory it is not rejected |
| Live end to end on Atlas (`scripts/smoke.py`, on a scratch copy) | The 39 checks from before round two: 39 of 39 with round two in place, script unchanged. With the 15 round-two checks added: 54 of 54 |
| Crash after the verdict, then resume (demo 3, live) | The run was marked interrupted, resumed by its owner, and finished. The resumed attempt made one model call (locating the finding on the image, 2,086 input tokens); reading the image, the claims and the verdict were reused from their checkpoints. Ledger chain intact across the crash |
| Crash after filing, then rollback (live) | The ad the dead run had filed was removed from the library; the chain verified |
| Lesion test (demo 3, live) | The control repeat reproduced the original verdict. With the Jake Moreau Slack decision removed, the result changed from rejected to approved: recorded as decisive. Two verdict calls, 16 s |
| Conflict (demo 3, live) | Recorded: `REG-03` (whose exception would allow a retired athlete in a responsible-gambling message) against the Slack decision; the Slack decision won |
| Flaw highlights, by eye | Demo 2, demo 3 and `NP-H12`: each box sat on the words or element the finding is about. Three ads is a small sample |
| Video (a 7-second test clip made for this, with speech and on-screen text) | Speech transcribed (21 words), 6 frames read, rejected on `REG-12` twice, `REG-13` and the Slack ban on "risk-free"; filed as a video; a follow-up question answered from it; regenerate declined as designed. 35 s |
| The demo video `demo_04_hockey_night_video.mp4` (15 s, `scripts/dry_run.py --video`, no database) | 6 frames read, the voice-over transcribed, approved with no findings. Confidence 75 because of the video discount, which is under the bar of 80, so it is routed to a person. 12 s after reading. The frames show the word "Honda" on the rink boards; worth a look by the data owner, since the data set is meant to carry no real brands |
| The agent, live (`POST /agent` as a manager, demo 3 in the library) | Goal: "Review the Play Smart breaks ad. If the policy calls for changes, update it, and then approve it for release." It chose: find the ad, review it (rejected on the Jake Moreau Slack decision, with the `REG-03` exception noted as overridden), regenerate with a voice-over (version 2 passed), approve (refused by the gate, `decided_by: initiator`). The reply cited the decision, its authors and date, the new version and the voice-over, and pointed to the Approve button. 5 turns, 109 s, 47,000 input tokens. The voice-over, transcribed back with ElevenLabs, says exactly the passing copy. Ledger chain intact (51 events) |
| The agent asked to approve (a manager, in chat, live) | Refused, with `decided_by: initiator` on the ledger |
| Consolidation (live) | Four drafts from the seeded past verdicts (`REG-14` from 7, `REG-12` from 5, `REG-09` from 4, `REG-06` from 3). Each read as a fair summary; none was saved |
| Regenerate | Demo 3 is regenerated as a new banner without the athlete and passes the same review |

**`NP-H05`** (the opted-in bonus email, recorded as approved) is rejected today on two points: the creative shows no unsubscribe option (`REG-15`), and it says "any NFL game" after Legal's 20 October message that NorthPlay holds no NFL marks. Whether that is right is a call for Alton, who holds the answer keys.

**Not verified:** the three demo ads against Alton's answer keys beyond what the README states; how traces look in LangSmith; that two users' same-named conversations stay separate (it follows from how thread ids are built, but nothing tests it). From round two: disabling a user mid-run, a run over its budget, an in-doubt step being adopted, and the strength arithmetic are covered by offline tests only, not live; a real process kill (as opposed to the staged crash) was not tried; video was tried on one short clip made for the purpose, and not on mov or webm; the web app's use of any new field.

**Not built:** reuse of a stored verdict for an unchanged ad, and the "review our policies for gaps" request.

## Measured

| | |
|---|---|
| One image review | About 9 to 14 s and 10,000 to 12,000 input tokens (image reading 2,000 to 3,500, claims 2,100, verdict 6,000 to 8,000) |
| Verdict effort | `LLM_EFFORT=low`. Raising it to `medium` made reviews about three times slower with the same findings on the ads tried |

## Things that will bite

- **Voyage rate limit.** An account without a payment method allows 3 requests and 10,000 tokens a minute. A review makes 2 embedding requests, so the app waits and retries when limited, and a live demo can stall. Adding a payment method in the Voyage dashboard lifts it; the free token allowance still applies.
- **Round-two fields need the new validators.** The `ledger` collection is strict. Run `scripts/load_db.py` once on any database made before round two, or the first `checkpoint` or `finding` event is rejected.
- **A crashed run is noticed after `RUN_STALE_SECONDS`** (120 by default) without a step reporting. A single step that runs longer than that, with someone looking at the run meanwhile, would be marked interrupted while still alive. Reviews take 10 to 40 seconds, so there is room, but do not set it below the slowest step.
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

### Added in round two

Everything above still behaves as it did. These are additions; adopt any of them or none.

| Topic | What the backend does |
|---|---|
| Flaws marked on an image | An image ad with findings comes back with `highlights: [{ finding, box, kind }]` and `annotated_url` on the report. `finding` is the index into `violations`; `box` is `[left, top, right, bottom]` as fractions of width and height, or null for something that is missing from the image. `annotated_url` is a ready-made copy with numbered boxes and a legend; fetch it like any asset. `GET /campaigns/{id}/annotated` returns both for the current version. Boxes come from a vision model and are approximate |
| Video | `POST /assets` accepts mp4, mov and webm up to 50 MB and returns `type: "video"`. Review it like any file. The ad's `modality` is `video`, `text` holds `Spoken: …` and `On screen: …`, there are no highlights, and regenerate returns `status: "failed"` with an explanation (the report still carries a corrected script) |
| Conflicts between sources | `report.conflicts: [{ between: [{type, ref, label}], winner: {type, ref, label}, explanation }]`, for example a regulation's exception against a newer Slack decision |
| Why a button is disabled | `POST /authorize { action, campaign_id?, initiator? }` → `{ allow, decided_by, reason, checks }`. Nothing is done or written. `decided_by` is `identity`, `role`, `initiator`, `state`, `limits`, or `all` when allowed |
| The rules | `GET /policies/actions` → every action with its `roles`, `initiators`, `preconditions`, `step_up` and a note, plus `limits_per_run` |
| Approving in chat | A manager asking the assistant to approve gets a fixed reply pointing to the button, with `status: "completed"`; the ledger records a `deny` with `decided_by: "initiator"` |
| The audit trail | `GET /audit` and `/audit/stream` are unchanged by default. Add `detail=true` for `model_call`, `retrieval`, `finding`, `conflict` and `attribution` events. New in the default view: `checkpoint`, `crash_detected`, `resume`. Decision events now also carry `decided_by`, `checks`, `initiator`, `span_id`; every event carries `seq`, `prev_hash`, `hash` |
| Is the record intact | `GET /audit/verify?run_id=` → `{ events, chained, intact, head }`, or `intact: false` with `first_bad_seq` and `problem` |
| A run as a tree | `GET /runs/{id}/trace` → `{ run, plan, steps, chain }`. Each step has its `decision`, `outcome` and `inside` (the model calls and retrievals made during it) |
| A run's state | `GET /runs/{id}` now also returns `steps` (each step's status), `plan`, `usage`, `attempt` and `resumable`. New status: `interrupted` |
| Crash recovery | `POST /runs/{id}/resume` (the run's owner only) continues an `interrupted` or `error` run and returns what the original request would have, plus `resumed: true` and `attempt`. `POST /runs/recover` marks stalled runs and lists the resumable ones. `POST /runs/{id}/rollback` now also clears what a half-finished step left behind |
| Staging a crash | Start the backend with `ALLOW_FAULT_INJECTION=true RUN_STALE_SECONDS=5`, then send `X-Crash-After: <step>` on `/chat`, `/compliance/check` or `/campaigns/{id}/regenerate`. Steps: `read`, `review`, `annotate`, `file`, `remember`; for regenerate `copy`, `render`, `file`, `remember`. The request returns 500 `{ error: "crashed" }` and the run is left as a dead process would leave it. `/health` reports whether this is on |
| Which memory caused the verdict | `POST /runs/{id}/attribution` on a chat or check run → `{ original, control, control_reproduced_original, tested: [{ memory_id, text, source, effect, causal, explanation, with, without, findings_lost }] }`. `effect` is `decisive`, `contributing`, `none` or `not_testable`. It repeats the verdict up to four times, so allow 15 to 40 seconds. 409 when no finding rests on a memory |
| Memory strength | `GET /memories` items carry `strength`. `GET /memories/fading` lists team memories that have faded, with `current_strength`; `POST /memories/{id}/confirm` (manager) restores one. Approve and reject now also adjust the strength of the memories the review used; a reject of an ad the review had passed stores the feedback as a memory |
| Lessons from past verdicts | `POST /memories/consolidate` (manager) → `{ proposals: [{ policy_key, episode_count, pattern_found, explanation, episodes, card }] }`. `card` is a `memory_change` card with `consolidated_from`; save it with `POST /memories` including `consolidated_from` and the password |
| Disabling a team member | `GET /users` (manager) lists the team. `POST /users/{id}/access { status: "disabled" or "active", password, reason }`. It takes effect at the next step of anything that person has running, and their tokens stop working: expect 403 `denied` with a message asking them to sign in again |
| New error | 500 `{ error: "crashed" }` only under fault injection |
