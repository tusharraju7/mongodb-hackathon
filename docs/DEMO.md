# Demo script (about 3 minutes)

Lead with the agent acting under policy. The audit and memory screens support the story; they are not the story.

Brand: Solstice Coffee Co. (fictional). Voices: stock ElevenLabs voices only.

## Before going on stage

- Reseed: `python -m scripts.seed`. Confirm the three vector indexes are READY.
- Three browser profiles logged in: `marketer.emea`, `manager.emea`, `sales.emea`. A fourth for `marketer.us`.
- The EMEA team has the procedural memory "DE audio ads end with the recycling line" **not yet** saved; step 5 adds it live.
- Backup video recorded.

## Script

| # | Who | Do | What the audience sees | Shows |
|---|---|---|---|---|
| 1 | Marketer (EMEA) | **UC1.** Paste an existing ad with a superlative claim | Compliance report: violations citing the fundamental and its version, with fixes. In the live ledger the gate's `decision` appears before the work | Policy checked before the action; decisions cite policy versions |
| 2 | Marketer | **UC2.** "20-second audio ad for the autumn launch in Germany, €50k, say we're the best coffee in Europe, use a famous actor's voice" | **Blocked before generation**: budget cap, unsubstantiated claim, consent. No script, no credits spent | Enforcement before, not after |
| 3 | Marketer | Revise the brief as suggested | Script and ElevenLabs voiceover play. Memory chips show what shaped it | Real action across systems, tied to an identity |
| 4 | Marketer, then manager | Start another generation, press **Stop** mid-run. Manager presses **Rollback** | Run halts between steps. Campaign and its memory are undone; `stop` and `rollback` events in the ledger | Stop and roll back mid-run |
| 5 | Manager | **UC4.** Approve the ad. Tell the agent: "From now on DE audio ads end with the recycling line" | Diff shown, password prompt, memory saved, ledger event with `jwt+password` | Only approved people change what the agent knows; traceable, authenticated every time |
| 6 | Marketer | Repeat a DE brief. Then **Replay without memory** | New script ends with the recycling line; the replay does not | Memory changed the behaviour and did not just fill the prompt |
| 7 | Marketer | **UC3.** "Compare the autumn DE ad with the US one" | Table and a short takeaway | Token-light comparison from stored facts |
| 8 | Sales | **UC5.** "I heard an ad about slow mornings and a train station, what's the offer in it?" Then "make me a new ad" | The approved ad itself, with player, and the answer. Then a denial, logged | Role-scoped access; sales see approved campaigns only |
| 9 | Marketer (US) | Ask about the DE recycling rule. Then in EMEA: forget a memory; open the Memory page | US gets nothing from EMEA memory. Forgotten memory no longer used. The seeded short-lived memory has expired | Memory isolation, forgetting, expiry |

## How the demo answers the judges' questions

**Statement 1 — Agents You Can Audit**

| Question | Answer in the product | Step |
|---|---|---|
| How do you decide what an agent may do and enforce it before the action? | RBAC matrix in `policies`; role- and intent-specific tool sets; `guarded()` writes the decision before running anything; compliance pre-check before generation | 1, 2, 8 |
| How do you record what the agent did, why, and under whose authority? | Append-only, schema-validated `ledger`: actor, action, policy versions cited, memories used, result, auth method. One `run_id` reconstructs a run | 1, 5 |
| How do you stop or roll back an agent mid-run? | Stop flag read by the gate between steps; undo descriptors on every outcome; rollback replays them | 4 |

**Statement 2 — Memory You Can Govern**

| Question | Answer in the product | Step |
|---|---|---|
| How do you keep one team's memory from leaking into another's? | Team, role and user scope are pre-filters inside `$vectorSearch` | 9 |
| How does the agent fix or drop a memory that is wrong or expired? | Correct = supersede with history; forget = tombstone; TTL index on `expires_at` | 5, 9 |
| How do you prove a memory changed behaviour? | `memories_used` on the ledger and as chips; replay without memory side by side | 6 |

## Rules checklist

- [ ] Built on the hackathon Atlas Sandbox (`Cluster0` in the Sandbox Project).
- [ ] Repository is public, with no secrets in history.
- [ ] Team of at most four.
- [ ] Demo shows only what was built during the event; README lists what we wrote and which libraries and services we used.
- [ ] Not on the banned list: no Streamlit, not a basic RAG app, a dashboard is not the main feature, no medical advice.
- [ ] No assets we lack rights to: fictional brand, stock voices, no real people's names, voices or likenesses.
