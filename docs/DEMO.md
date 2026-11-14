# Demo script (about 3 minutes)

Lead with the agent acting under policy: it blocks, regenerates a compliant version, and gates a release. The audit and memory screens support the story; they are not the story.

Setting: Tamarack Bank, a fictional Canadian bank, advertising the Tamarack Cashback Card. Offer `TCB-FALL-2026`: 0% on purchases for 10 months, then 20.99%; $300 cash back after $1,500 in purchases in 90 days. Sample audio was produced with stock ElevenLabs voices; sample banners were rendered from our own brand template.

Submission form: it takes one track. Proposed primary track is **Agents You Can Audit**, with governed memory supporting it. Confirm as a team before submitting.

## Before going on stage

- Reseed: `python -m scripts.seed`. Confirm the three vector indexes are READY.
- Browser profiles logged in: `marketer.national`, `manager.national`, `marketer.quebec`, `manager.quebec`, `sales.national`.
- An audio file of the running example as a radio spot: "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."
- A released display banner for the same offer in the library (for step 5).
- A second national ad already approved but not released (for step 4).
- A French Quebec ad that passes today and does not contain "Sous réserve de l'approbation du crédit." (for step 3).
- The Quebec team instruction is **not yet** saved; step 3 adds it live.
- Backup video recorded.

## Script

| # | Who | Do | What the audience sees | Shows |
|---|---|---|---|---|
| 1 | Marketer (national) | **UC1, audio in.** Upload the radio spot. Offer `TCB-FALL-2026` | The gate's decision appears in the live ledger first. ElevenLabs transcribes the spot. Then: blocked, routed to human review, with a plain summary and a confidence score with its reasons. Findings cite the policy and version: approval promise; 12 months against an approved 10; missing later rate; missing bonus conditions; missing required line. Open one finding to show its reasoning, evidence and confidence | Policy checked before the action; findings cite versions; the ad is checked against the system of record |
| 2 | Marketer, then manager (national) | **Regenerate compliant version.** Play it. Manager approves. Marketer releases | The corrected script is reviewed first and passes; only then does ElevenLabs produce the new audio. Version 2 plays. Approval is stored with the ad version and policy versions. Release succeeds | A real action across systems, taken only after the check passes; approval bound to what was reviewed |
| 3 | Manager, then marketer (Quebec) | **UC4.** "From now on, Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'" Then review the prepared French ad, and **Replay without memory** | Before/after, password prompt, saved; ledger shows `jwt+password`. The ad is now flagged, citing the instruction. The replay passes | Only approved people change what the agent knows, authenticated every time. Memory changed the behaviour |
| 4 | Manager, then marketer (national) | Edit `credit.intro_rate_disclosure` (password). Marketer tries to release the other approved ad. Manager presses **Rollback** on the edit | Release refused: approval is stale, the policy moved from version 3 to 4. After rollback, version 3 is restored and the `rollback` event is in the ledger | Enforcement before the action; rollback; versioned policy |
| 5 | Sales (national) | **UC5, image out.** "A customer saw a banner about $300 cash back on the card. What are the conditions?" Then "approve the Quebec ad" | The released banner itself, and the conditions from the offer record. Then a denial, logged | Role-scoped access; sales see released ads only; answers come from approved facts |
| 6 | Marketer (national) | Ask about the Quebec credit-approval line. Then in Quebec: forget a memory; open the Memory page | National gets nothing from Quebec memory. The forgotten memory is no longer used. The seeded short-lived memory has expired | Memory isolation, forgetting, expiry |

If time is short, show 1 → 2 → 3 → 5. Show only what is implemented.

If audio is not ready, run steps 1 and 2 with the same ad pasted as text; the flow is identical. Uploading an image ad for review is supported but is not a demo step (see below).

## How the demo answers the judges' questions

**Statement 1 — Agents You Can Audit**

| Question | Answer in the product | Step |
|---|---|---|
| How do you decide what an agent may do and enforce it before the action? | Role permissions in `policies`; role- and intent-specific tool sets; `guarded()` writes the decision before running anything; regeneration renders only copy that has passed; release re-checks the approval against current versions | 1, 2, 4, 5 |
| How do you record what the agent did, why, and under whose authority? | Schema-validated `ledger` of insert-only events: actor, action, policy versions cited, memories used, route, result, auth method. One `run_id` reconstructs a run | 1, 2, 3 |
| How do you stop or roll back an agent mid-run? | Stop flag read by the gate between steps; undo descriptors on every outcome; rollback replays them | 4 |

**Statement 2 — Memory You Can Govern**

| Question | Answer in the product | Step |
|---|---|---|
| How do you keep one team's memory from leaking into another's? | Team, role and user scope are filters inside the vector search | 6 |
| How does the agent fix or drop a memory that is wrong or expired? | Correct = supersede with history; forget = tombstone; TTL index on `expires_at`; policy clauses carry effective dates | 3, 6 |
| How do you prove a memory changed behaviour? | The verdict cites the memory id; the check is for an exact required line; replay without memory side by side | 3 |

## What to say, and what not to claim

- **Do not lead with image review.** "Image analyzers" are on the banned list. Reading an image ad is one input to the review workflow, alongside text and audio. Keep it out of the headline and out of the first minute.
- The confidence score is "evidence strength, computed in code". Do not call it a probability or an accuracy figure; the weights are not calibrated.
- A regenerated version "passes the same review as any other ad". It still needs a manager's approval. Do not say it is legally compliant.
- A regenerated audio or image is a new rendering that carries the corrected copy, not an edit of the original file.
- Stop takes effect between steps. A call to an outside service that is already in flight is not cancelled.
- Rollback undoes our own records (policy version, memory, ad version and its file). It does not undo an external call or refund credits.
- The ledger is insert-only in application code. Say "append-only by design"; claim database-enforced immutability only if task A6 shipped.
- Marketing compliance checking and brand memory exist in other products. Claim an original implementation built during the event, not a first.

## Rules checklist

- [ ] Built on the hackathon Atlas Sandbox, and the shared cluster is the event project, not a personal one.
- [ ] Repository is public, with no secrets in history.
- [ ] Team of at most four.
- [ ] Demo shows only what was built during the event; README lists what we wrote and which libraries and services we used.
- [ ] Not on the banned list: no Streamlit, not a basic RAG app, not an image analyzer, a dashboard is not the main feature, no medical advice.
- [ ] No assets we lack rights to: fictional bank and card, stock voices, our own banner template, no real institutions, card networks, people, voices or likenesses.
