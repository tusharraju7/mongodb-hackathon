"""Run the real review on an ad without the database.

Clauses, offers and memories come from backend/seed/*.json and are embedded in memory with Voyage.
The prompts, rules, retrieval ranking, confidence and routing are the same code the app runs.

    python -m scripts.dry_run                      # the running example, then its corrected copy
    python -m scripts.dry_run --ad qc-email-english-only
    python -m scripts.dry_run --text "..." --region CA-QC --channel email --language fr --as marketer.quebec@tamarack.test
    python -m scripts.dry_run --json               # print the full report as JSON
"""
from __future__ import annotations

import argparse
import json
import time
import uuid

from app.core import llm
from app.services import compliance
from app.services.fixture_sources import SeedSources, load_seed, seed_identity

RUNNING_EXAMPLE = "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."


def show(title: str, result: compliance.ReviewResult, usage: llm.TokenUsage, seconds: float, as_json: bool) -> None:
    r = result.report
    print(f"\n=== {title} ===")
    if as_json:
        print(json.dumps(r.model_dump(), indent=2, ensure_ascii=False))
        return
    print(f"verdict: {r.verdict}   route: {r.route}   confidence: {r.confidence.score} ({r.confidence.band})")
    print(f"route reason: {r.route_reason}")
    print(f"confidence reasons: {'; '.join(r.confidence.reasons)}")
    print(f"summary: {r.summary}")
    for v in r.violations:
        ref = v.fundamental_key or f"memory {v.memory_id}"
        ver = f" v{v.version}" if v.version else ""
        print(f"  - [{v.materiality}/{v.basis}] {ref}{ver}  conf {v.confidence.score}  quote: {v.quote!r}")
        print(f"      {v.explanation}")
        print(f"      fix: {v.fix}")
        print(f"      why {v.confidence.score}: {'; '.join(v.confidence.reasons)}")
    if r.passed_checks:
        print("passed: " + "; ".join(f"{p.check}" for p in r.passed_checks))
    if r.corrected_copy:
        print(f"corrected copy: {r.corrected_copy}")
    print(f"memories in view: {r.memories_used}")
    print(f"tokens: {usage.as_dict()}  steps: {[(c['step'], c['in'], c['out']) for c in usage.calls]}  time: {seconds:.1f}s")


def run(text: str, ctx: dict, identity, sources, *, use_memory: bool, title: str, as_json: bool) -> compliance.ReviewResult:
    usage = llm.TokenUsage()
    started = time.time()
    result = compliance.review(text, ctx, identity, str(uuid.uuid4()), use_memory=use_memory, sources=sources, usage=usage)
    show(title, result, usage, time.time() - started, as_json)
    return result


def ad_context(ad: dict) -> dict:
    return {k: ad.get(k) for k in ("product", "offer_id", "region", "channel", "language", "modality", "budget", "visual_notes")}


def suite(sources: SeedSources) -> None:
    """Review every seeded ad and compare the verdict with the one recorded in the seed file.

    Claims are extracted for all ads first and their search text embedded in a single request,
    which keeps the whole suite inside a three-requests-a-minute embedding limit.
    """
    from app.core import embeddings

    ads = load_seed("campaigns")
    usage = llm.TokenUsage()
    started = time.time()
    extractions = {ad["ref"]: compliance.extract_claims(ad["text"], ad_context(ad), usage=usage) for ad in ads}
    embeddings.embed_queries([q for ad in ads for q in [ad["text"]] + [c.quote for c in extractions[ad["ref"]].claims]])
    rows, failures = [], 0
    for ad in ads:
        identity = seed_identity(ad["created_by"])
        result = compliance.review(ad["text"], ad_context(ad), identity, str(uuid.uuid4()), sources=sources, usage=usage, extraction=extractions[ad["ref"]])
        r, expected = result.report, ad["compliance"]["verdict"]
        ok = (r.verdict == "pass") == (expected == "pass")
        failures += not ok
        cited = sorted({v.fundamental_key or f"memory:{v.memory_id}" for v in r.violations})
        rows.append((("ok  " if ok else "DIFF"), ad["ref"], expected, r.verdict, r.route, r.confidence.score, ", ".join(cited)))
    print(f"\n{'':4}  {'ad':28} {'expected':9} {'got':13} {'route':16} conf  cited")
    for mark, ref, expected, got, route, score, cited in rows:
        print(f"{mark}  {ref:28} {expected:9} {got:13} {route:16} {score:>4}  {cited}")
    print(f"\n{len(ads) - failures} of {len(ads)} agree with the seed file. tokens: {usage.as_dict()}  time: {time.time() - started:.0f}s")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", action="store_true", help="review every seeded ad and compare with its recorded verdict")
    p.add_argument("--ad", help="ref of a seeded ad in backend/seed/campaigns.json")
    p.add_argument("--text", help="ad copy to review")
    p.add_argument("--offer", default="TCB-FALL-2026")
    p.add_argument("--region", default="CA")
    p.add_argument("--channel", default="email")
    p.add_argument("--language", default=None)
    p.add_argument("--modality", default="text", choices=["text", "audio", "image"])
    p.add_argument("--budget", type=float, default=20000)
    p.add_argument("--as", dest="email", default=None, help="seeded user to act as")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    sources = SeedSources()
    if args.suite:
        suite(sources)
        return
    if args.ad:
        ad = next(a for a in load_seed("campaigns") if a["ref"] == args.ad)
        identity = seed_identity(args.email or ad["created_by"])
        run(ad["text"], ad_context(ad), identity, sources, use_memory=not args.no_memory, title=f"seeded ad {args.ad}", as_json=args.json)
        return

    identity = seed_identity(args.email or ("marketer.quebec@tamarack.test" if args.region == "CA-QC" else "marketer.national@tamarack.test"))
    ctx = {
        "product": "credit_card", "offer_id": args.offer, "region": args.region, "channel": args.channel,
        "language": args.language, "modality": args.modality, "budget": {"amount": args.budget, "currency": "CAD"},
    }
    text = args.text or RUNNING_EXAMPLE
    first = run(text, ctx, identity, sources, use_memory=not args.no_memory, title="submitted ad", as_json=args.json)
    if not args.text and first.report.corrected_copy:
        run(first.report.corrected_copy, {**ctx, "modality": "text"}, identity, sources, use_memory=not args.no_memory, title="its corrected copy, reviewed again", as_json=args.json)


if __name__ == "__main__":
    main()
