"""The lesion test: prove which memories changed a verdict.

Neuroscience learns what a region does by taking it out of action and watching what changes. The
same is done here. A finished review is repeated with one memory removed and everything else held
still: the same text, the same context, the same extracted claims, the same other memories. If the
verdict or a finding changes, that memory caused it. A control repeat with nothing removed shows
how much of any difference is just the judge varying from one call to the next.
"""
from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core import llm
from app.models import ComplianceReport, Extraction, Identity
from app.services import compliance, memory
from app.services.compliance_rules import norm

MAX_LESIONS = 3


class NothingToTest(Exception):
    pass


def _same_finding(finding, report: ComplianceReport) -> bool:
    """Is this finding still raised, on whatever basis? Matched by the words of the ad it points at."""
    quote = norm(finding.quote or "")
    if not quote:
        return False
    return any(quote in norm(v.quote or "") or norm(v.quote or "") in quote for v in report.violations if (v.quote or "").strip())


def _brief(report: ComplianceReport) -> dict:
    return {"verdict": report.verdict, "decision": report.decision, "route": report.route, "findings": len(report.violations), "confidence": report.confidence.score}


def lesion_test(identity: Identity, run_id: str, reviewed: dict, *, sources=None, usage: Optional[llm.TokenUsage] = None, db=None) -> dict:
    """`reviewed` is the stored result of the original run's review step."""
    if not reviewed or not reviewed.get("extraction"):
        raise NothingToTest("This run has no stored review to repeat.")
    original = ComplianceReport(**reviewed["report"])
    extraction = Extraction(**reviewed["extraction"])
    text, ctx = reviewed["text"], reviewed["ctx"]
    in_view = memory.load_for_review(identity, original.memories_used, db)
    by_id = {m["id"]: m for m in in_view}
    # The memories a finding rests on are the ones worth testing; the rest were only in view.
    cited = list(dict.fromkeys(v.memory_id for v in original.violations if v.memory_id))
    if not cited:
        raise NothingToTest("No finding in this review rests on a memory, so there is nothing to remove.")

    def judge(memories: list[dict]) -> ComplianceReport:
        return compliance.review(text, dict(ctx), identity, run_id, sources=sources, usage=usage, extraction=extraction, memories=memories).report

    control = judge(in_view)  # first and alone: it also warms the embedding cache for the repeats
    testable = [m for m in cited if m in by_id][:MAX_LESIONS]
    with ThreadPoolExecutor(max_workers=max(1, len(testable))) as pool:
        futures = {m: pool.submit(contextvars.copy_context().run, judge, [x for x in in_view if x["id"] != m]) for m in testable}
        lesioned = {m: f.result() for m, f in futures.items()}

    results = []
    for memory_id in cited[:MAX_LESIONS]:
        if memory_id not in by_id:
            results.append({"memory_id": memory_id, "effect": "not_testable", "explanation": "This memory can no longer be read (forgotten, expired or corrected since)."})
            continue
        m, without = by_id[memory_id], lesioned[memory_id]
        rested = [v for v in control.violations if v.memory_id == memory_id]
        lost = [v for v in rested if not _same_finding(v, without)]
        verdict_changed = (without.verdict, without.route) != (control.verdict, control.route)
        effect = "decisive" if without.verdict != control.verdict else "contributing" if (lost or verdict_changed) else "none"
        explanation = {
            "decisive": f"Without this memory the result changes from {control.decision or control.verdict} to {without.decision or without.verdict}.",
            "contributing": f"Without this memory {len(lost)} finding(s) are no longer raised, though the overall result stays {control.decision or control.verdict}.",
            "none": "Without this memory the same findings are raised on other grounds, so it did not change the result.",
        }[effect]
        results.append({
            "memory_id": memory_id, "text": m["text"], "standing": m["authority"], "source": m.get("source_label"), "date": m.get("date"),
            "effect": effect, "causal": effect != "none", "explanation": explanation,
            "with": _brief(control), "without": _brief(without),
            "findings_lost": [{"quote": v.quote, "explanation": v.explanation} for v in lost],
        })

    reproduced = control.verdict == original.verdict
    drift = [c for c in original.checked_fundamentals if c not in control.checked_fundamentals]
    return {
        "original": _brief(original), "control": _brief(control), "control_reproduced_original": reproduced,
        "policies_changed_since": drift, "memories_in_view": len(in_view), "tested": results,
        "note": None if reproduced else "The control repeat, with nothing removed, did not give the original verdict. Read the effects below against the control, and treat them with care.",
    }
