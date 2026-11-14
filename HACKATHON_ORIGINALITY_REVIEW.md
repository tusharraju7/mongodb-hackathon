# Greenlight: originality and hackathon fit review

Reviewed November 14, 2026 against main commit 223f3fac7702ba9fd37ee1f4650ced2b5b72904b. This is a design and prior-art review, not verification of implemented behavior or organizer eligibility approval.

## Confirmed project

Greenlight is a governed marketing agent that reviews creative, turns an approved brief into a script and ElevenLabs voiceover, compares campaigns, answers campaign questions, and lets a manager change governed memory.

Source: [FLOWS.md, UC2 and supporting flows](https://github.com/tusharraju7/mongodb-hackathon/blob/223f3fac7702ba9fd37ee1f4650ced2b5b72904b/docs/FLOWS.md#uc2--new-creative-from-a-prompt).

This replaces the previous PM status that the idea was unconfirmed. The local Chelsea-setup branch lacked the newer main planning documents. At the inspected commit, main contained documentation rather than application implementation. This does not establish what teammates have on unmerged branches or their laptops.

## Verdict

Proceed with the concept, with implementation and evidence gates open. Marketing generation, brand-rule checking, approval and persistent brand context are established capabilities. We should claim an original event-built implementation and demonstrate its specific behavior, not claim to have invented marketing AI or to be the first governed marketing agent.

Recommended primary submission track: **Agents You Can Audit**. The form requires one track. Governed memory can support the story; the recommendation does not replace a team track decision.

## Comparison with existing work

| Source reviewed | Documented overlap | Implication for Greenlight |
| --- | --- | --- |
| [Jasper IQ](https://www.jasper.ai/jasper-iq) | Persistent brand context applied across generation workflows; brand-rule checks | Brand memory and on-brand generation alone are not a novelty claim |
| [Wondercraft audio ads](https://www.wondercraft.ai/ads) | AI copy/audio creation and team approval flows | Prompt-to-script-to-voice and approval alone are not a novelty claim |
| [marketing-compliance-gate](https://github.com/portable-genai/marketing-compliance-gate/blob/main/README.md) | Deterministic marketing rule checks, cited findings, maker-checker approval, auditability | A compliance gate with citations also has public prior art |

These are comparisons of published descriptions, not source-code similarity findings or proof of copying. Do not claim these systems lack a feature just because a selected page does not mention it. Search also surfaced relevant Devpost entries, but full-page retrieval failed; those were not relied on for the verdict. The search is bounded and cannot establish universal uniqueness.

## What the demo should prove

A credible proposed contribution is an Atlas-backed marketing workflow in which the same run can be traced from identity and current policy through authorization, generated output, external voice generation, and the exact governed memories used.

Show a short sequence:
1. A disallowed role or brief is rejected before paid voice generation; an audit event explains why.
2. An authorized compliant brief produces a real voiceover, linked to the run and policy versions.
3. A manager changes a team instruction with step-up verification; the next run follows it.
4. Another team cannot retrieve that instruction. Corrected, forgotten or expired memory is excluded.
5. Stop prevents the next external action; if rollback is implemented, show exactly which local artifacts are compensated.

The strongest evidence is observable behavior and persisted records, not an audit dashboard or a list of memory IDs. Compare the same brief with and without the relevant instruction under controlled settings; check for the exact required line. Mere random output differences are not evidence of memory causality.

## Rule fit

- **Basic RAG:** UC1 review and UC5 Q&A alone risk looking like the excluded category. The core demo must show enforced action permissions, actual generation and governed state changes.
- **Dashboard as main feature:** The repository's demo already says audit/memory screens support the action. Preserve that emphasis.
- **Streamlit:** Planned Next.js/FastAPI stack avoids this exclusion; verify final implementation.
- **Image analyzer / other prohibited topics:** Current text-and-audio marketing flow does not appear to fall into those categories. Avoid adding an image-analysis-led feature or medical-advice examples.
- **Original work:** README disclosure placeholders must be completed with actual event-built features, dependencies, datasets/assets, team members and any earlier preparation. Do not assert all work was inside the official build window without checking provenance.
- **Sandbox:** The earlier UI check identified Chelsea's personal Cluster0. The main design's label “Atlas Sandbox” is a requirement, not proof that the active connection uses the event organization. Reverify the shared project before sign-off.

Final category eligibility remains the organizer's decision.

## Concrete planning findings

1. **UC2 has an unspecified failure branch after script generation.** FLOWS.md shows a post-check immediately followed by ElevenLabs, without an explicit failing-post-check branch. Specify fail-closed behavior: fail/error/unknown means no TTS, no campaign approval, and a blocked outcome. Acceptable brief → violating generated script must be covered by a meaningful test.
2. **Protect the distinguishing features in the build order.** PLAN.md puts UC3 comparison before UC4 memory editing. Move the minimal authorized correction → changed-next-run demonstration ahead of comparison and general Q&A. This is a recommendation for stream owners, not a change to their files.
3. **Do not claim database-enforced append-only storage prematurely.** README calls the ledger append-only, but PLAN.md places database permissions/hash chaining in P2. If only application conventions enforce append-only behavior, say so. Schema validation alone does not prove immutability.
4. **Define stop and rollback boundaries honestly.** Stop between steps cannot necessarily cancel an already dispatched provider request. Removing a campaign/audio/memory locally cannot refund consumed TTS credits or undo external processing. Demonstrate local compensation and retain audit history.
5. **Correct the cost wording.** UC2 says a blocked brief spends no credits, but the same document allows a judge model call. Say “no ElevenLabs generation credits”; log any review/router token use separately.
6. **Resolve the time-box mismatch.** PLAN.md says all P0 merged at T+2:30, while B4 and D4 are P0 scheduled through T+3:00. Assign realistic integration deadlines before the 5 PM external submission deadline.
7. **Keep scope small.** The nine-step live script is ambitious for three minutes. Lead with deny → corrected brief → voiceover → authorized memory change → changed next run, with short audit evidence. Show only implemented extras.

References: [PLAN.md](https://github.com/tusharraju7/mongodb-hackathon/blob/223f3fac7702ba9fd37ee1f4650ced2b5b72904b/docs/PLAN.md), [DEMO.md](https://github.com/tusharraju7/mongodb-hackathon/blob/223f3fac7702ba9fd37ee1f4650ced2b5b72904b/docs/DEMO.md), [README](https://github.com/tusharraju7/mongodb-hackathon/blob/223f3fac7702ba9fd37ee1f4650ced2b5b72904b/README.md), [event rules](https://cerebralvalley.ai/e/mongodb-toronto-hackathon/details#5-hackathon-rules-5).

## Status

Concept identified; initial prior-art comparison complete. Implementation, exact original contributions, final primary-track choice, event sandbox identity, README attribution, and organizer clarification of early setup-only commits remain open. Do not treat this review as final originality or eligibility certification.
