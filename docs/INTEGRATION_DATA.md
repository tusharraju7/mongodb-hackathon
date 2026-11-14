# Greenlight integration data and change control

Verified from seed files and read-only Atlas counts on 2026-11-14.

| Data | Count | Purpose |
| --- | --- | --- |
| Regulatory clauses (`fundamentals`) | 15 | Rules applied to ads, versioned separately from memories |
| Historical projects (`campaigns`) | 15 | Ad text/assets, findings, versions and human status |
| Memories | 60 | 26 Slack-derived, 19 deck-derived, 15 past-decision records |
| Raw Slack messages | 49 | Provenance |
| Strategy documents | 2 | Provenance/background |
| Accounts | 7 | Team and role access |
| Permission policies | 3 | Allowed actions by role |
| Offer records | 0 | NorthPlay does not require an offer picker |
| Local image readings | 15 | Cached extraction for historical-ad fixtures |
| Demo creatives | 3 | Local images, uploaded explicitly for live review |

Memory kinds: 31 semantic, 14 procedural, 15 episodic. Standing: 10 binding, 4 guidance, 15 precedent, 31 background.

## Inputs and outputs

Image input becomes ImageReading (text, visual notes, fine-print presence/legibility, people present). Text becomes Extraction (claims and literal quotes, CTA, language, tone, description, summary). The judge returns findings with source references, quotes, explanation, reasoning, fixes and certainty, plus conflicts and corrected copy. Code validates references/quotes and produces ComplianceReport: verdict, decision, confidence, route, findings, passed checks, policy versions, memory IDs and prompt version.

Confidence is evidence strength, not a risk/readiness percentage. Image coordinates and readiness are not in the current backend schema. Human campaign status is distinct from the model's recommendation. Live PDF/video analysis is not implemented by this frontend.

## What changes

The Greenlight agent is the Python/LangGraph route-and-lane workflow, not a second hosted model. OpenAI replaces the Claude model calls; MongoDB, Voyage retrieval, permissions, gate and ledger remain.

Ordinary review recalls scoped memories and updates their usage counters. Saving a non-passing review with memory enabled can add a 30-day episodic memory. Saved campaigns/versions and audit events change; LLM weights do not. An approve/reject click stores a human decision and optional feedback; it does not train the model or turn feedback into a binding policy.

Explicit memory change: draft a memory_change card → authorize/confirm with password for team-wide edits → call the appropriate write endpoint → record the action. Correction creates a new record and supersedes the old; forgetting keeps a tombstone excluded from active retrieval. Stop and rollback endpoints exist; rollback cannot undo external API charges. The frontend currently displays review/chat results, but does not yet provide memory-change approval controls.

## Comparison and limits

The preserved Opus/Haiku baseline is RESULTS.md, prompt version 2026-11-14.3. New OpenAI comparisons must use a separate results path and the same role, channel, source snapshot and memory setting. The historical suite excludes each ad's own prior verdict from retrieval. A model match is not legal validation.

Shared Atlas contents were inspected without writes. MongoDB and Voyage connectivity succeeded; billing balances are not exposed by these application checks. An OpenAI key and valid existing login credentials remain required for live review generation. No OpenAI result has been generated during this integration yet.
