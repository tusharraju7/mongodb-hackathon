# Greenlight — a marketing agent you can audit, with memory you can govern

MongoDB hackathon project. Team of 4, built in 4 hours.

Greenlight is a marketing agent for an organisation. It reviews existing ad creative, as text, audio or image, against policy clauses and the approved offer record. On request it regenerates a version that passes the same review, in the ad's own form (ElevenLabs for audio, a brand template for images), and it gates release on a current approval. It lets the marketing manager update what the agent knows and remembers, and answers questions about an ad by returning the ad itself. It runs on NorthPlay, a fictional Ontario sportsbook: 15 advertising regulations, 15 past ad decisions, and Slack decisions that are binding and stricter than the regulations. MongoDB Atlas is the identity, policy, audit and memory layer:

- **Agents You Can Audit** — every action is tied to an identity, checked against policy before it runs, and written to an append-only ledger. Runs can be stopped and rolled back.
- **Memory You Can Govern** — memory lives in Atlas with Vector Search (Voyage embeddings), scoped per team and role, with expiry, correction and forgetting, and a visible trace of which memories changed a result.

**Status:** the backend is built and the `greenlight` database is loaded with the NorthPlay data. Verified: 52 offline tests; 14 of 15 past ads match their recorded decision; the three demo ads come out as intended; 38 of 39 live end-to-end checks, with the one failure fixed and re-checked. The web app is in progress. See [docs/BACKEND.md](docs/BACKEND.md).

## Documents

| | |
|---|---|
| [AGENTS.md](AGENTS.md) | Guidance for every coding agent: ownership, rules, branching |
| [docs/PLAN.md](docs/PLAN.md) | Execution plan: streams, tasks, time boxes, checks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Tech stack, infrastructure diagram, core mechanisms |
| [docs/FLOWS.md](docs/FLOWS.md) | Operational flows for the three use cases: auth, memory, token use |
| [docs/WORKED_EXAMPLE.md](docs/WORKED_EXAMPLE.md) | One credit card ad followed from policy document to release, with sample JSON |
| [docs/BACKEND.md](docs/BACKEND.md) | The backend as built: how to run it, what is verified, what data and the web app must match |
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
