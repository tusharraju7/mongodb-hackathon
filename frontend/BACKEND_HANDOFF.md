# Optional agent-output contract

This proposal is consumed by the React adapter but **is not implemented in the inspected backend**. Existing reports work without these fields. The backend team can add them to `ComplianceReport`, preserve them when filing campaigns, and return them in direct review, chat report cards and full campaign responses.

```json
{
  "readiness_score": {
    "value": 75,
    "scale": 100,
    "rubric_version": "readiness-v1"
  },
  "annotations": [
    {
      "id": "annotation-1",
      "finding_ref": "REG-12",
      "label": "Public bonus offer",
      "kind": "issue",
      "box": {"x": 0.075, "y": 0.544, "width": 0.73, "height": 0.083}
    }
  ]
}
```

- Coordinates are fractions of the **original displayed image**, top-left origin, between 0 and 1. Account for EXIF orientation before returning boxes. Do not send pixel values with this format. `x + width` and `y + height` must not exceed 1.
- `kind: issue` renders a red rectangle; `evidence` is revealed on selection. Supply human-readable labels and a `finding_ref` matching the violation's `fundamental_key` (or `memory_id`) or a passed-check reference. A future unique finding ID is preferable when several findings cite one rule.
- Only return coordinates actually grounded in the image. Missing content is usually a document-level finding, not a fabricated region. Current UI does not invent live boxes.
- `readiness_score` is distinct from `confidence`. Define and version its rubric, including how all assets are aggregated. Current UI treats 80+ as the nominal submission threshold, but any unresolved verdict still requires acknowledgement. A high score cannot bypass a blocked verdict or manager approval requirements.
- Never use model output to grant roles, publish an ad or override server authorization. The backend must enforce approval conditions independently of the UI.

## Backend work still needed for the complete proposed flow

1. Produce and validate image annotations; persist them with the exact image/version.
2. Produce a rubric-based readiness score; do not rename confidence.
3. Add submit-existing-assessment with an immutable assessment ID, explicit unresolved-findings acknowledgement and idempotency. Current frontend must call `check(save=true)` again; the new report may differ.
4. Persist full analysis history per ad version, including policy versions, source references, annotations and reviewer rationale. Add private transcript retrieval if chat must resume across devices.
5. Add PDF/video extraction before enabling those formats for live review. Define page numbers and timestamps when extending annotation coordinates.
6. If intended, adapt the live policy sources from Tamarack credit cards to NorthPlay and test them against the demo examples.
7. Before anonymous/public live use, verify application rate limits, atomic per-user and global budget reservations, concurrency caps, input/output limits and a fail-closed kill switch. Record actual usage after each provider call and reconcile reservations. Provider throttling and a remaining-credit display do not enforce a total spend ceiling.

Current frontend behavior: explicit role login; real backend authorization; `save=false` assessment then `save=true` submission; manager decisions via dedicated endpoints; no automatic release. Review errors, expired sessions, HTTP 429 and blocked approvals are shown without pretending success.
