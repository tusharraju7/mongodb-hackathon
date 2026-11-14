# Greenlight

**A marketing agent you can audit, with memory you can govern.**

MongoDB hackathon project · Team of 4 · Built in 4 hours

Every ad a regulated business runs has to clear legal review. Today that means a lawyer reading each ad against the regulations, past decisions, the brand plan and whatever was agreed in Slack last week. Greenlight is an agent that does the first pass, shows its work, and hands the final call to the lawyer.

## What it does

A marketer uploads an ad as **text, audio or image**. The agent:

1. **Reads it.** Audio is transcribed (ElevenLabs Scribe) and images are read once. Every format becomes text and goes through the same review.
2. **Gathers the right context.** It picks which regulations apply, then searches past ad decisions, strategy decks and team Slack decisions, scoped to the marketer's team.
3. **Reasons across conflicts.** When sources disagree (the regulation allows it, a past ad was approved, but Legal banned it in Slack last week), it says so and explains which source wins.
4. **Recommends and acts.** It returns a verdict with findings that each cite their source, drafts a compliant version on request, and routes the ad.
5. **Hands off to a human.** The marketer submits to Legal: a green **Submit** at 90% confidence or higher, a red **Submit anyway** below 90%. Only the lawyer can approve or reject, and release is blocked until a current approval exists.

Every step is tied to an identity, checked against policy before it runs, and written to the ledger.

## Two screens

| Marketer | Lawyer (lawyer role only) |
|---|---|
| Upload on the left; the agent's live step trace, findings and recommendation on the right; confidence and Submit at the bottom | The same view of the submitted ad and the agent's analysis, plus **Approve** / **Reject** of the final recommendation |

Confidence is **evidence strength, computed in code** from how the findings are supported. It is not a probability, and it can only make the route stricter, never looser.

## Demo scenario

The demo uses **NorthPlay**, a fictional Ontario sportsbook. Its data, generated as test data for the event, is in [`northplay-demo-data/`](northplay-demo-data/):

- 15 sportsbook advertising rules: fictional, modelled on Ontario-style standards, not legal advice
- 15 past ad decisions with rationale
- 2 strategy decks (2027 strategy, Q1 2027 marketing plan)
- A Slack export with internal decisions that are newer and stricter than the decks
- 3 ads for the live demo

The planning documents in [`docs/`](docs/) were written with a fictional bank example; the flows are the same. [docs/BACKEND.md](docs/BACKEND.md) describes the backend as built on the NorthPlay data.

## Built on MongoDB Atlas

Atlas is the identity, policy, audit and memory layer, and covers both problem statements:

- **Agents You Can Audit:** every action is tied to an identity, checked against policy before it runs, and written to a ledger that is append-only by design. Runs can be stopped and rolled back.
- **Memory You Can Govern:** memory lives in Atlas with Vector Search (Voyage embeddings), scoped per team and role. It expires, can be corrected or forgotten, and each result shows which memories changed it.

## Stack

Next.js · FastAPI · LangGraph / LangChain · Claude (verdict and fast models) · MongoDB Atlas (Vector Search, change streams, schema validation, TTL, GridFS) · Voyage AI embeddings · ElevenLabs (Scribe speech-to-text, text-to-speech) · MongoDB MCP server

## Status

The backend is built and the `greenlight` database on Atlas is loaded with the NorthPlay data. The web app is in progress.

Checked so far: 77 offline tests pass; 14 of the 15 past ads come back with their recorded decision when reviewed without the memory of that decision; the three demo ads come out as intended; and 54 of 54 live end-to-end checks passed on Atlas, including a staged crash that was resumed and then rolled back. Details, limits and how to run it are in [docs/BACKEND.md](docs/BACKEND.md); why the gate, the ledger and the memory work the way they do is in [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

## Documents

| | |
|---|---|
| [AGENTS.md](AGENTS.md) | Guidance for every coding agent: ownership, rules, branching |
| [docs/PLAN.md](docs/PLAN.md) | Execution plan: streams, tasks, time boxes, checks |
| [docs/BACKEND.md](docs/BACKEND.md) | The backend as built: the NorthPlay data, how to run it, what is verified, API notes for the web app |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Tech stack, infrastructure diagram, core mechanisms |
| [docs/FLOWS.md](docs/FLOWS.md) | Operational flows: auth, memory, token use |
| [docs/WORKED_EXAMPLE.md](docs/WORKED_EXAMPLE.md) | One ad followed from policy to release, with sample JSON |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Schemas, indexes, RBAC matrix, API, service signatures |
| [docs/MONGODB_SETUP.md](docs/MONGODB_SETUP.md) | Collections, validators, indexes, creation order, seed data |
| [docs/SETUP.md](docs/SETUP.md) | Shared Atlas Sandbox access, environment, MCP |
| [docs/DEMO.md](docs/DEMO.md) | Demo script and rules checklist |

## Built during the hackathon

Everything in this repository was written during the event. To be completed before submission:

- **What we built:** _list the features shown in the demo_
- **Third-party libraries and services used:** _see Stack; confirm before submitting_
- **Team:** _names_
