# Operational flows

Three use cases, in build priority order. For each: the flow, how it authenticates, what memory it reads and writes, and how it keeps token use low.

> UC2 (create new creative from a prompt) and UC3 (compare campaigns) were dropped from scope. The remaining ids are kept as UC1, UC4, UC5.

**Setting.** Solstice Coffee Co. is a fictional Canadian coffee roaster with two marketing teams: `national` (English Canada) and `quebec`. Ads carry a region: `CA` or `CA-QC`. A Quebec ad is checked against global rules, Canadian rules and Quebec rules; a national ad against global and Canadian rules.

**Roles.** `manager` = marketing manager (the approved person), `marketer`, `sales`.

## Access matrix

| Use case | manager | marketer | sales | Step-up password |
|---|---|---|---|---|
| UC1 Review existing creative | yes | own team | no | no |
| UC4 Memory updates | yes | personal notes only | no | every change |
| UC5 Questions about an ad | yes | yes | approved ads only | no |

## Front door (shared by every use case)

```mermaid
flowchart TD
  IN["Message + JWT"] --> AUTH["1 AUTH<br/>verify JWT, load identity: user, role, team<br/>code, 0 tokens"]
  AUTH -->|"invalid token"| R401["401"]
  AUTH --> ROUTE["2 ROUTE<br/>intent classifier on the fast model, about 150 tokens<br/>offered only the intents this role may use"]
  ROUTE --> ACCESS{"3 ACCESS<br/>policy gate:<br/>does the role hold the action?"}
  ACCESS -->|"no"| DENY["Fixed denial text<br/>ledger event: deny<br/>no further model call"]
  ACCESS -->|"yes"| SCOPE["4 SCOPE<br/>load this intent's tools only<br/>lookups pre-filtered by team, role, status"]
  SCOPE --> UC1["UC1 Review existing creative"]
  SCOPE --> UC4["UC4 Memory updates"]
  SCOPE --> UC5["UC5 Questions about an ad"]
  UC1 --> REC["6 RECORD<br/>ledger outcome, memory write if any<br/>reply with cards, tokens logged on the run"]
  UC4 --> REC
  UC5 --> REC
```

| Intent | Action checked at the gate | Tools loaded |
|---|---|---|
| `review` | `compliance.check` (and `campaign.submit` when the creative is saved) | `review_creative` |
| `memory_update` | `fundamentals.update`, `memory.write`, `memory.forget` | `update_memory`, `forget_memory`, `review_fundamentals` |
| `ask` | `campaign.ask` | `ask_about_ad` |

## UC1 — Existing creative review

A marketer or manager pastes ad copy, uploads an audio ad (ElevenLabs Scribe transcribes it), or names an ad already in the library.

Example: a national ad that says *"Solstice. Canada's best coffee. 100% Product of Canada."* with a CAD 50,000 budget is blocked on three counts: an unsupported superlative, an origin claim coffee cannot meet (the fix offered is "Roasted in Canada from imported beans"), and a budget over the team cap.

```mermaid
sequenceDiagram
  autonumber
  actor U as Marketer or manager
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant E as ElevenLabs
  participant V as Voyage
  participant L as LLM
  U->>API: Ad copy, audio file or library ad, with JWT
  API->>DB: Look up the user (users) and whether the role may review (policies)
  API->>DB: Write the allow decision to the ledger before any work
  opt audio file
    API->>E: Transcribe the audio (Scribe)
    E-->>API: Transcript
  end
  API->>API: Hard rules in code - budget cap, banned terms, required lines
  API->>V: Turn the ad text into a vector
  API->>DB: Find the 5 closest company rules for the ad's regions, summaries only (fundamentals_vec)
  API->>DB: Find up to 3 team instructions and past verdicts, own team, not expired (memories_vec)
  API->>DB: Is there a stored report for this exact text, these rule versions and these memories
  alt stored report exists
    DB-->>API: Stored report, no model tokens
  else no stored report
    API->>L: Judge the ad against the rules and memories (main model, structured output)
    L-->>API: Verdict and violations, each citing a rule key and version, or a memory id
  end
  opt creative is new to the library
    API->>L: Extract a summary and facts once (fast model)
    API->>DB: Save the ad as pending_review with its report (campaigns)
  end
  API->>DB: Save a memory of this verdict, expiring in 30 days (memories)
  API->>DB: Write the outcome to the ledger - rules cited, memories used, tokens
  API-->>U: Compliance report card with fixes
```

- **Authentication:** JWT. Role must hold `compliance.check`. A library ad must belong to the caller's team.
- **Memory read:** semantic (the company rules), procedural (the manager's standing instructions for this team), episodic (past verdicts on similar ads).
- **Memory written:** episodic, expiring in 30 days.
- **Tokens:** hard rules and both lookups cost no model tokens; a stored report skips the judge; the judge sees five rule summaries and three short memories; summary and facts are extracted once and reused by UC5.

## UC4 — Memory updates by the marketing manager

Covers: a new standing instruction, editing a company rule, correcting a memory, forgetting a memory.

Example: the Quebec manager says *"From now on, Quebec audio ads must end with 'Torréfié au Québec'."* The next review of a Quebec audio ad without that line is flagged, citing this instruction.

The agent only drafts the change. The password goes from the browser straight to the write endpoint and never passes through the model.

```mermaid
sequenceDiagram
  autonumber
  actor M as Marketing manager
  participant WEB as Web app
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant L as LLM (fast model)
  M->>WEB: Instruction or edit
  WEB->>API: Chat message with JWT
  API->>DB: Look up the user and role
  alt role is not manager
    API->>DB: Write the deny decision to the ledger
    API-->>WEB: Denied. Marketers may only save notes scoped to themselves
  else role is manager
    API->>L: Draft the change as a structured before and after
    L-->>API: Proposed change
    API-->>WEB: Proposed change card
    WEB-->>M: Show the diff, ask for password and reason
    M->>WEB: Confirm with password (asked on every change)
    WEB->>API: Write endpoint with JWT, password and reason
    API->>DB: Verify the password (users)
    API->>DB: Write the allow decision to the ledger, auth method jwt+password
    alt company rule
      API->>DB: Keep the old version (fundamentals_versions), save version + 1, re-embed
    else memory
      API->>DB: Save the new memory and mark the old one superseded, or mark it forgotten
    end
    API->>DB: Write the outcome to the ledger - before, after, reason, undo descriptor
    API-->>WEB: Confirmed, with the new version
  end
```

- **Authentication:** JWT plus password re-entry for every single change. The ledger records `auth.method = jwt+password`. Sales cannot write. Marketers can save notes with `scope.user_id` set to themselves, without step-up.
- **Memory read:** the item being changed.
- **Memory written:** semantic (company rules, team facts) and procedural (standing instructions). Old versions are kept.
- **Tokens:** one small drafting call on the fast model. The write, versioning and re-embedding are code.

## UC5 — General questions about an ad

Also handles "I heard an ad about …": the agent returns the ad itself.

Example: a sales rep asks *"I heard an ad about slow mornings at Union Station, what's the offer in it?"* and gets the approved ad with its player, plus the answer.

```mermaid
sequenceDiagram
  autonumber
  actor U as Any role
  participant API as Backend (auth, router, gate)
  participant DB as Atlas (greenlight)
  participant V as Voyage
  participant L as LLM (fast model)
  U->>API: Question about an ad, with JWT
  API->>DB: Look up the user and whether the role may ask (policies)
  API->>DB: Write the allow decision to the ledger
  alt the conversation already refers to an ad
    API->>DB: Read the last ad discussed in this thread (checkpoints)
  else needs lookup
    API->>V: Turn the question into a vector
    API->>DB: Find the closest ad this role and team may see (campaigns_vec)
  end
  DB-->>API: Summary and facts for that one ad
  alt answerable from summary and facts
    API->>L: Answer from the facts, about 300 tokens in
  else needs the full text
    API->>DB: Load the text of that one ad
    API->>L: Answer from the text
  end
  L-->>API: Answer
  API->>DB: Write the outcome to the ledger
  API-->>U: Answer and the ad card with player
```

- **Authentication:** JWT. All roles. Sales are limited to approved ads of their own team by the query filter, so an unapproved ad can never be returned to them.
- **Memory read:** short-term (the conversation) to resolve "the ad".
- **Memory written:** none.
- **Tokens:** one ad, facts first, full text only when needed, fast model.

## Token rules (apply to every flow)

1. **Deny before spending.** Authentication and role checks are code. A refused request costs at most the router call.
2. **One intent, one small tool set.** The model never sees tool schemas for flows the role or the intent does not need.
3. **Filter before retrieving.** Team, role, region and status are filters inside the vector search. Out-of-scope documents cost nothing and cannot leak.
4. **Summaries, not documents.** `summary` (60 words or fewer) and `facts` are computed once at write time. Full text is loaded only for the item being cited or edited. Embeddings are never returned.
5. **Fixed lookup budgets.** Company rules 5, memories 3, ads 1.
6. **Code before model.** Hard rules, diffs and versioning are code.
7. **Model tiering.** The main model is used only for the compliance verdict. Router, Q&A, extraction and drafting use the fast model.
8. **Reuse verdicts.** Reports are stored under a key built from the ad text, the versions of the rules consulted and the ids of the memories recalled. Any change to those produces a fresh verdict.
9. **Trim the conversation.** The last 6 turns plus a rolling summary go to the model. Full history stays in `checkpoints`.
10. **Measure.** `intent` and `tokens.in` / `tokens.out` are logged on every `runs` document and shown in the audit view.
