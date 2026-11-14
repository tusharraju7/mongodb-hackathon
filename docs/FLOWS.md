# Operational flows

Five use cases, in build priority order. For each: the flow, how it authenticates, what memory it reads and writes, and how it keeps token use low.

Roles: **manager** = marketing manager (the approved person), **marketer**, **sales**.

## Access matrix

| Use case | manager | marketer | sales | Step-up password |
|---|---|---|---|---|
| UC1 Review existing creative | yes | own team | no | no |
| UC2 Create from a prompt | yes | yes | no | no |
| UC3 Compare campaigns | yes | yes | approved only | no |
| UC4 Memory updates | yes | personal notes only | no | every change |
| UC5 Questions about an ad | yes | yes | approved only | no |

## Front door (shared by every use case)

```mermaid
flowchart TD
  IN["Message + JWT"] --> AUTH["1 AUTH<br/>verify JWT, load identity: user, role, team<br/>code, 0 tokens"]
  AUTH -->|"invalid token"| R401["401"]
  AUTH --> ROUTE["2 ROUTE<br/>intent classifier on the fast model, about 150 tokens<br/>offered only the intents this role may use"]
  ROUTE --> ACCESS{"3 ACCESS<br/>policy gate:<br/>does the role hold the action?"}
  ACCESS -->|"no"| DENY["Fixed denial text<br/>ledger event: deny<br/>no further model call"]
  ACCESS -->|"yes"| SCOPE["4 SCOPE<br/>load this intent's tools only<br/>retrieval pre-filtered by team, role, status"]
  SCOPE --> UC1["UC1 Review existing creative"]
  SCOPE --> UC2["UC2 Create from a prompt"]
  SCOPE --> UC3["UC3 Compare campaigns"]
  SCOPE --> UC4["UC4 Memory updates"]
  SCOPE --> UC5["UC5 Questions about an ad"]
  UC1 --> REC["6 RECORD<br/>ledger outcome, memory write if any<br/>reply with cards, tokens logged on the run"]
  UC2 --> REC
  UC3 --> REC
  UC4 --> REC
  UC5 --> REC
```

| Intent | Action checked at the gate | Tools loaded |
|---|---|---|
| `review` | `compliance.check` | `review_creative` |
| `create` | `asset.generate` | `generate_ad`, `review_creative` |
| `compare` | `campaign.compare` | `compare_campaigns` |
| `memory_update` | `fundamentals.update`, `memory.write`, `memory.forget` | `update_memory`, `forget_memory`, `review_fundamentals` |
| `ask` | `campaign.ask` | `ask_about_ad` |

## UC1 — Existing creative review

A marketer or manager pastes an ad, names a stored campaign, or (P1) uploads audio that ElevenLabs Scribe transcribes.

```mermaid
sequenceDiagram
  autonumber
  actor U as Marketer or manager
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant V as Voyage
  participant L as LLM (fast model)
  U->>API: Ad text or campaign id, with JWT
  API->>DB: users - resolve identity
  API->>DB: policies - is compliance.check allowed for this role
  API->>DB: ledger - decision allow, written before any work
  API->>DB: Cached report for this text and these fundamentals versions
  alt cache hit
    DB-->>API: Stored report, no model tokens
  else cache miss
    API->>API: Hard rules in code - budget cap, voice allow-list, banned terms, disclaimers
    API->>V: Embed ad text as a query
    API->>DB: fundamentals_vec - region is global or the ad region, top 5, summaries only
    API->>DB: memories_vec - episodic, own team, not expired, top 3
    API->>L: Judge with structured output
    L-->>API: Verdict and violations, each citing a fundamental key and version
    API->>DB: Store report on the campaign, write episodic memory with 30-day expiry
  end
  API->>DB: ledger - outcome with policy refs, memories used, tokens
  API-->>U: Compliance report card with fixes
```

- **Authentication:** JWT. Role must hold `compliance.check`. A stored campaign must belong to the caller's team.
- **Memory read:** semantic (fundamentals), episodic (past verdicts on similar ads).
- **Memory written:** episodic, expiring in 30 days.
- **Tokens:** cache hit costs nothing; hard rules run in code first; the judge sees five summaries and three short memories; fast model.

## UC2 — New creative from a prompt

```mermaid
sequenceDiagram
  autonumber
  actor U as Marketer or manager
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant L as LLM
  participant E as ElevenLabs
  U->>API: Brief, with JWT
  API->>DB: Resolve identity, check asset.generate, write decision
  API->>API: UC1 pre-check on the brief
  alt brief is not compliant
    API->>DB: ledger - outcome blocked, run status blocked
    API-->>U: Violations and fixes, asks the user to revise. Nothing generated, no credits spent
  else brief passes
    API->>DB: memories_vec - procedural top 3, preferences top 2, scoped to team and role
    API->>L: Write the script (main model, the only step that uses it)
    L-->>API: Script
    API->>API: UC1 post-check on the script
    API->>E: Text to speech with an allow-listed voice
    E-->>API: Audio
    API->>DB: GridFS - store audio
    API->>L: Extract summary and facts once (fast model)
    API->>DB: campaigns - save as pending_review with embedding
    API->>DB: memories - write episodic memory of this run
    API->>DB: ledger - outcome with undo descriptor and memories used
    API-->>U: Campaign card with player, compliance report, memory chips
  end
```

- **Authentication:** JWT. Role must hold `asset.generate` (manager, marketer). Each step is a separate gated action, so the stop flag is honoured between steps.
- **Memory read:** procedural (how this team wants ads written), semantic preferences. Their ids are recorded as `memories_used`.
- **Memory written:** episodic.
- **Tokens:** a blocked brief costs one judge call; the main model is used once; summary and facts are extracted once and reused by UC3 and UC5.

## UC3 — Comparing current campaigns

```mermaid
sequenceDiagram
  autonumber
  actor U as Any role
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant L as LLM (fast model)
  U->>API: Compare the autumn DE ad with the US one, with JWT
  API->>DB: Resolve identity, check campaign.compare, write decision
  API->>DB: campaigns_vec - pre-filter team and the statuses this role may see, top 2 to 4
  DB-->>API: summary, facts, compliance verdict, status only
  API->>DB: memories_vec - semantic preferences, top 2
  API->>API: Build the comparison table in code
  API->>L: Write a 3 to 5 sentence takeaway over the table
  L-->>API: Takeaway
  API->>DB: ledger - outcome
  API-->>U: Comparison table, takeaway, campaign cards
```

- **Authentication:** JWT. Manager and marketer see all statuses of their own team. Sales see `approved` only. The status filter is in the query.
- **Memory read:** semantic preferences (what this team cares about when comparing).
- **Memory written:** none.
- **Tokens:** about 100 tokens per campaign (stored facts) instead of full scripts; the table is code; no embeddings are ever returned.

## UC4 — Memory updates by the marketing manager

Covers: a new standing instruction ("from now on DE audio ads end with the recycling line"), editing a fundamental, correcting a memory, forgetting a memory.

```mermaid
sequenceDiagram
  autonumber
  actor M as Marketing manager
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant L as LLM (fast model)
  M->>API: Instruction or edit, with JWT
  API->>DB: Resolve identity
  alt role is not manager
    API->>DB: ledger - decision deny
    API-->>M: Denied. Marketers may only save notes scoped to themselves
  else role is manager
    API->>L: Draft the change as a structured before and after
    L-->>API: Proposed change
    API-->>M: Show the diff, ask for password and reason
    M->>API: Confirm with password (asked on every change)
    API->>DB: users - verify password, auth method becomes jwt+password
    API->>DB: ledger - decision allow for fundamentals.update, memory.write or memory.forget
    alt fundamental
      API->>DB: Snapshot old version to fundamentals_versions, version + 1, re-embed
    else memory
      API->>DB: New memory supersedes the old one, or old one marked forgotten
    end
    API->>DB: ledger - outcome with before, after, reason, undo descriptor
    DB-->>API: Change stream on fundamentals invalidates cached compliance reports
    API-->>M: Confirmation with the new version
  end
```

- **Authentication:** JWT plus password re-entry for every single change. The ledger records `auth.method = jwt+password`. Sales cannot write. Marketers can save notes with `scope.user_id` set to themselves, without step-up.
- **Memory read:** the item being changed.
- **Memory written:** semantic (fundamentals, team facts) and procedural. Old versions are kept.
- **Tokens:** one small drafting call. The write, versioning and re-embedding are code.

## UC5 — General questions about an ad

Also handles "I saw an ad about …": the agent returns the ad itself.

```mermaid
sequenceDiagram
  autonumber
  actor U as Any role
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant L as LLM (fast model)
  U->>API: What is the call to action in the train-station ad, with JWT
  API->>DB: Resolve identity, check campaign.ask, write decision
  alt the thread already refers to a campaign
    API->>DB: checkpoints - last campaign discussed in this thread
  else needs lookup
    API->>DB: campaigns_vec - pre-filter team and allowed statuses, top 1
  end
  DB-->>API: summary and facts for that one campaign
  alt answerable from facts and summary
    API->>L: Answer from facts, about 300 tokens in
  else needs the script
    API->>DB: Load the script of that one campaign
    API->>L: Answer from the script
  end
  L-->>API: Answer
  API->>DB: ledger - outcome
  API-->>U: Answer and the campaign card with player
```

- **Authentication:** JWT. All roles. Sales are limited to approved campaigns of their team by the query filter.
- **Memory read:** short-term (thread) for reference resolution.
- **Memory written:** none.
- **Tokens:** one document, facts first, script only when needed, fast model.

## Token rules (apply to every flow)

1. **Deny before spending.** Authentication and RBAC are code. A refused request costs at most the router call.
2. **One intent, one small tool set.** The model never sees tool schemas for flows the role or the intent does not need.
3. **Filter before retrieving.** Scope lives in the `$vectorSearch` pre-filter. Out-of-scope documents cost nothing and cannot leak.
4. **Summaries, not documents.** `summary` (60 words or fewer) and `facts` are computed once at write time. Full text is loaded only for the item being cited or edited. Embeddings are never projected.
5. **Fixed retrieval budgets.** Fundamentals 5, memories 3, campaigns 4.
6. **Code before model.** Hard rules, comparison tables and diffs are computed in code.
7. **Model tiering.** The main model writes scripts. Router, judge, Q&A and extraction use the fast model.
8. **Cache compliance reports** by hash of the content plus the versions of the fundamentals consulted.
9. **Trim short-term memory.** The last 6 turns plus a rolling summary go to the model. Full history stays in `checkpoints`.
10. **Measure.** `intent` and `tokens.in` / `tokens.out` are logged on every `runs` document and shown in the audit view.
