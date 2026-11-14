# Greenlight — a marketing agent you can audit, with memory you can govern

MongoDB hackathon project. Team of 4, built in 4 hours.

Greenlight is a marketing agent for an organisation. It reviews existing ad creative, as text, audio or image, against policy clauses and the approved offer record. On request it regenerates a version that passes the same review, in the ad's own form (ElevenLabs for audio, a brand template for images), and it gates release on a current approval. It lets the marketing manager update what the agent knows and remembers, and answers questions about an ad by returning the ad itself. The examples use a fictional Canadian bank advertising a cashback credit card, with a national team and a Quebec team. MongoDB Atlas is the identity, policy, audit and memory layer:

- **Agents You Can Audit** — every action is tied to an identity, checked against policy before it runs, and written to an append-only ledger. Runs can be stopped and rolled back.
- **Memory You Can Govern** — memory lives in Atlas with Vector Search (Voyage embeddings), scoped per team and role, with expiry, correction and forgetting, and a visible trace of which memories changed a result.

**Status:** planning complete; implementation starts at kickoff. This repo currently contains the plan and the guidance for the team's coding agents.

## Documents

| | |
|---|---|
| [AGENTS.md](AGENTS.md) | Guidance for every coding agent: ownership, rules, branching |
| [docs/PLAN.md](docs/PLAN.md) | Execution plan: streams, tasks, time boxes, checks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Tech stack, infrastructure diagram, core mechanisms |
| [docs/FLOWS.md](docs/FLOWS.md) | Operational flows for the three use cases: auth, memory, token use |
| [docs/WORKED_EXAMPLE.md](docs/WORKED_EXAMPLE.md) | One credit card ad followed from policy document to release, with sample JSON |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Schemas, indexes, RBAC matrix, API, service signatures |
| [docs/MONGODB_SETUP.md](docs/MONGODB_SETUP.md) | Collections, validators, indexes, creation order and seed data |
| [docs/SETUP.md](docs/SETUP.md) | Shared Atlas Sandbox access, environment, MCP |
| [docs/DEMO.md](docs/DEMO.md) | Demo script and rules checklist |

## Stack

Next.js · FastAPI · LangGraph / LangChain · MongoDB Atlas (Vector Search, change streams, schema validation, TTL, GridFS) · Voyage AI embeddings · ElevenLabs · MongoDB MCP server

## Built during the hackathon

Everything in this repository was written during the event. To be completed before submission:

- **What we built:** _list the features shown in the demo_
- **Third-party libraries and services used:** _list_
- **Team:** _names_
