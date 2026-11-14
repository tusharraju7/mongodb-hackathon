# Demo script (about 3 minutes)

Lead with the agent acting under policy. The audit and memory screens support the story; they are not the story.

Brand: Solstice Coffee Co., a fictional Canadian roaster with a national team and a Quebec team. Sample audio was produced with stock ElevenLabs voices.

## Before going on stage

- Reseed: `python -m scripts.seed`. Confirm the three vector indexes are READY.
- Browser profiles logged in: `marketer.national`, `marketer.quebec`, `manager.quebec`, `sales.national`.
- Two audio files ready to upload: an English-only spot aimed at Montreal, and its French version without the closing line "Torréfié au Québec".
- The Quebec team instruction about the closing line is **not yet** saved; step 3 adds it live.
- Backup video recorded.

## Script

| # | Who | Do | What the audience sees | Shows |
|---|---|---|---|---|
| 1 | Marketer (national) | **UC1.** Paste: "Solstice. Canada's best coffee. 100% Product of Canada." Budget CAD 50,000 | Blocked on three counts, each citing a rule and its version: unsupported superlative, origin claim (fix offered: "Roasted in Canada from imported beans"), budget over the cap. In the live ledger the gate's decision appears before the work | Policy checked before the action; decisions cite rule versions |
| 2 | Marketer (Quebec) | **UC1, audio.** Upload the English-only Montreal spot. Then upload the French version | ElevenLabs transcribes it. First upload is flagged under the Quebec French-language rule. The French version passes and is saved to the library as pending review | Real action across systems, tied to an identity; region decides which rules apply |
| 3 | Manager (Quebec) | **UC4.** "From now on, Quebec audio ads must end with 'Torréfié au Québec'." | Before/after shown, password prompt, memory saved, ledger event with `jwt+password` | Only approved people change what the agent knows; authenticated every time and traceable |
| 4 | Marketer (Quebec) | Review the same French ad again. Then **Replay without memory** | Now flagged, citing the manager's instruction. The replay passes | Memory changed the behaviour and did not just fill the prompt |
| 5 | Manager (Quebec) | Edit the Quebec budget cap. Then **Rollback** that run | Password prompt, version 2, history. After rollback, version 1 text is restored; `rollback` event in the ledger | Stop and roll back; versioned policy |
| 6 | Manager, then sales (national) | Manager approves the Union Station ad. Sales: **UC5.** "I heard an ad about slow mornings at Union Station, what's the offer in it?" Then "raise the budget cap" | The approved ad itself, with player, and the answer. Then a denial, logged | Role-scoped access; sales see approved ads only |
| 7 | Marketer (national) | Ask about the Quebec closing-line rule. Then in Quebec: forget a memory; open the Memory page | National gets nothing from Quebec memory. The forgotten memory is no longer used. The seeded short-lived memory has expired | Memory isolation, forgetting, expiry |

Optional, if time allows: press **Stop** during an audio review in step 2 to show the run halting between transcription and the verdict.

## How the demo answers the judges' questions

**Statement 1 — Agents You Can Audit**

| Question | Answer in the product | Step |
|---|---|---|
| How do you decide what an agent may do and enforce it before the action? | Role permissions in `policies`; role- and intent-specific tool sets; `guarded()` writes the decision before running anything | 1, 6 |
| How do you record what the agent did, why, and under whose authority? | Append-only, schema-validated `ledger`: actor, action, rule versions cited, memories used, result, auth method. One `run_id` reconstructs a run | 1, 3 |
| How do you stop or roll back an agent mid-run? | Stop flag read by the gate between steps; undo descriptors on every outcome; rollback replays them | 5 |

**Statement 2 — Memory You Can Govern**

| Question | Answer in the product | Step |
|---|---|---|
| How do you keep one team's memory from leaking into another's? | Team, role and user scope are filters inside the vector search | 7 |
| How does the agent fix or drop a memory that is wrong or expired? | Correct = supersede with history; forget = tombstone; TTL index on `expires_at` | 3, 7 |
| How do you prove a memory changed behaviour? | The verdict cites the memory id; `memories_used` on the ledger and as chips; replay without memory side by side | 4 |

## Rules checklist

- [ ] Built on the hackathon Atlas Sandbox (`Cluster0` in the Sandbox Project).
- [ ] Repository is public, with no secrets in history.
- [ ] Team of at most four.
- [ ] Demo shows only what was built during the event; README lists what we wrote and which libraries and services we used.
- [ ] Not on the banned list: no Streamlit, not a basic RAG app, a dashboard is not the main feature, no medical advice.
- [ ] No assets we lack rights to: fictional brand, stock voices, no real people's names, voices or likenesses.
