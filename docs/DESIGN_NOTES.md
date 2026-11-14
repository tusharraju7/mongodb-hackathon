# Design notes: where the ideas come from

Round two added crash recovery, a finer and tamper-evident audit trail, pre-action authorisation, and a memory that changes with use. Each mechanism below is borrowed from somewhere: established engineering practice for the audit side, and how human memory behaves for the memory side.

The memory ideas are **inspired by** neuroscience. They are not a model of the brain, and every number in them is a starting value, not a tuned one.

How to run and call all of this is in [BACKEND.md](BACKEND.md). This page is the why.

## What an agent may do, decided before it acts

One function, `authorize()` in `backend/app/core/gate.py`, is called by `guarded()` before every step with a side effect. It asks five questions in order. The first that fails decides, and the refusal is written to the ledger with the name of the check, before anything runs.

| # | Check | Question | Where the answer lives | Example of a refusal |
|---|---|---|---|---|
| 1 | Identity | Is this still an active user, with the role and team their token says? | `users` (`status`, `role`, `team`, `auth_version`), re-read at every step | A marketer disabled while their review is running loses authority at the next step |
| 2 | Role | Does the role hold this action? | `policies` | Support asks for a review |
| 3 | Initiator | May the agent take this action, or only a person? | `action_rules.initiators` | A manager asks the assistant in chat to approve an ad |
| 4 | Scope and state | Is the target in the user's team, and in a state that allows this? | `action_rules.preconditions`, checked against the target | Releasing an ad whose approval is stale |
| 5 | Limits | Is the run within its budget? | `action_rules._limits`, against `runs.usage` | A run that has made 20 model calls |

Three things follow from putting it in one place:

- **The model never decides.** It classifies what was asked for. Code maps that to an action and asks `authorize()`. The model never sees the rules and cannot change them.
- **The rules are data.** `policies` and `action_rules` are collections in Atlas. A reviewer can read them, and a rule can be tightened there without a deploy. The defaults in `gate.py` apply where a rule has no document.
- **Nothing starts on a plan that would fail.** A lane declares the steps it intends to take; all are checked before the first one runs, and the plan is stored on the run. Each step is still checked again when it executes, because a user's standing and an ad's state can change in between.

`POST /authorize` answers "could this be done, and which check decides" without doing it or writing anything. It calls the same function as the real action.

## The audit trail

| Practice | What it is | What is built |
|---|---|---|
| **Write-ahead logging** (databases) | Record the intent before making the change, so a crash can never leave a change with no record | The `decision` event is on the ledger before the action runs. The `outcome` follows. A decision with no outcome means the step did not finish |
| **Event sourcing, append-only logs** | State is a sequence of facts that are added, never edited | `ledger` is insert-only. A correction is a new event (`rollback`), never an edit |
| **Hash chains** (certificate transparency, git) | Each entry carries a fingerprint of the one before it, so history cannot be quietly rewritten | Every event has `seq`, `prev_hash` and `hash` (SHA-256 over its content). `GET /audit/verify?run_id=` recomputes the chain and names the first event that was edited, removed or inserted. A unique index on `(run_id, seq)` stops two writers from forking it |
| **Provenance: who, did what, to which thing, on whose authority** (W3C PROV) | An audit record names the agent, the activity and the entity | Every event has the `actor` from the signed token, the `action`, the target in `params` and `result.ref`, the `auth.method`, the `initiator` (person or agent), and the `checks` that allowed it |
| **Traces and spans** (OpenTelemetry) | A request is a tree of timed operations | Each step has a `span_id` and `duration_ms`; a model call or retrieval inside it carries `parent_span_id`. `GET /runs/{id}/trace` returns the run as that tree |
| **Sagas with compensating actions** (distributed transactions) | A long operation is a series of steps, each with a way to undo it | Each `outcome` carries an `undo` descriptor. Rollback replays them newest first |
| **Idempotency keys and checkpoints** (workflow engines) | A step with a stable key is done at most once, however many times the workflow is retried | Each step of a lane has a fixed `step_key`. Its result is stored in `runs.steps`. A resumed run reuses it and does not call the model again |

Event types: `decision`, `outcome`, `stop`, `rollback`, `checkpoint`, `crash_detected`, `resume` in the default view; `model_call`, `retrieval`, `finding`, `conflict`, `attribution` with `?detail=true`.

One choice worth stating. The ledger holds **pointers and fingerprints, not copies**. A `model_call` event has the model, the prompt version, token counts, latency and a hash of the prompt and of the answer; the text itself is in the trace. The ledger stays small and holds nothing it should not, and it can still prove which prompt produced which answer.

## Crash recovery

A run can die at any point: the process is killed, the machine restarts, a model or embedding call fails.

| Situation | What happens |
|---|---|
| A step finished before the crash | Its result is in `runs.steps`. On resume it is returned as is, and a `checkpoint` event says so. No model is called for it again |
| A step was started and never recorded as finished | It may or may not have taken effect. Everything a step creates carries the run id (the ad version, the memory, the file), so the step first looks for its own effect. Found: it is kept. Not found: the step runs. Either way the effect exists exactly once |
| The process died | The run is still marked `running` but has stopped reporting. It is marked `interrupted` at server start, when someone looks at it, or on `POST /runs/recover`; a `crash_detected` event records how far it got |
| A model or embedding call failed | The run ends as `error`. It can be resumed the same way, which matters on a rate-limited account: the verdict is not paid for twice |

`POST /runs/{id}/resume` continues from the last completed step. Only the person who started the run can resume it, and every remaining step goes through `authorize()` again, so someone who lost the right since the crash cannot finish the run. `POST /runs/{id}/rollback` undoes it instead, including whatever a half-finished step left behind.

For a demo or a test, `ALLOW_FAULT_INJECTION=true` and the request header `X-Crash-After: <step>` abandon a run right after that step, exactly as a dead process would leave it. It is off by default.

## Memory, borrowing from how people remember

| Idea | In people | What is built | Where |
|---|---|---|---|
| **Lesion test** | What a brain region does is established by taking it out of action and seeing what changes. Correlation is not enough | `POST /runs/{id}/attribution` repeats a finished review with one memory removed and everything else held still: the same text, context, claims and other memories. If the verdict changes, the memory was **decisive**; if only its finding disappears, **contributing**; if the same finding is raised on other grounds, it had **no effect**. A control repeat with nothing removed shows how much the judge varies by itself | `services/attribution.py` |
| **Conflict monitoring** | Competing signals are noticed before acting, and the conflict itself is information | The judge reports where its sources disagree (a regulation allows it, a past ad was approved, a Slack decision bans it), which one won and why. Each is a `conflict` event. A background memory or past verdict that loses to a binding decision is marked `contested_by` it, and is labelled as contested the next time it is recalled | `services/compliance.py`, `services/memory.py` |
| **Reinforcement and surprise** | What is confirmed gets stronger. An outcome that was not expected is remembered more strongly than a routine one | Each memory has a `strength`. A manager approving an ad the review passed strengthens the memories that review used. A manager rejecting an ad the review passed weakens them, and the manager's reason is stored as a memory stronger than a routine one | `routers/campaigns.py`, `memory.reinforce` |
| **Forgetting** | What is not used fades. Fading is useful: it keeps old detail from crowding out what matters now | Past verdicts and background fade with a half-life (45 and 90 days) from when they were last confirmed or used. **Binding decisions and guidance never fade.** Strength only nudges which memories are put in view, by at most a few hundredths of a similarity point. `GET /memories/fading` lists what has faded for a manager to confirm or let go | `memory.current_strength` |
| **Consolidation** | Single episodes are distilled over time into general knowledge | `POST /memories/consolidate` groups past verdicts that turned on the same rule and drafts one standing lesson per group, linked to the verdicts it came from. Nothing is saved until a manager confirms a draft with their password | `services/consolidation.py` |
| **Source monitoring** | Knowing where a memory came from, and telling a memory from an inference | Every finding must cite a clause or a memory that was actually in front of the judge, and quote words that are actually in the ad. Anything else is dropped in code | `services/compliance.py` |
| **Index, not content** | Some structures hold pointers to a memory, not the memory itself | The ledger points at memories, clauses and prompts by id, version and hash. It does not copy them | `core/gate.py` |

What strength cannot do: change what a memory says, waive a policy clause, or let a faded binding decision drop out of view. Policy still outranks memory, and the route still comes from the findings in code.

## Limits

- The hash chain proves the ledger was not edited after the fact. It does not stop someone with database write access from rewriting a whole run and recomputing every hash; that needs the chain head published somewhere the writer cannot reach.
- A lesion test repeats a model call, and a model can vary between calls. The control repeat makes that visible; when it does not reproduce the original verdict the result says so.
- Resume repeats the paid external call of a step that was in flight when the run died (a transcription, say), unless that step left a file behind to find.
- The strength numbers are starting values. Nothing here has been tuned on real usage.
