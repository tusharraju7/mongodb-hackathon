"""Run the real review on an ad without the database.

Clauses, memories and past ads come from backend/seed/*.json and are embedded in memory with Voyage.
The prompts, rules, retrieval ranking, confidence and routing are the same code the app runs.

    python -m scripts.dry_run --suite                       # every past ad against its recorded decision
    python -m scripts.dry_run --ad NP-H07                   # one past ad
    python -m scripts.dry_run --image ../northplay-demo-data/demo_ads/demo_02_big_game_bonus.png --channel "Instagram (paid social)"
    python -m scripts.dry_run --text "Sign up today and get $500 in bonus bets!" --channel "Instagram (paid social)"
    python -m scripts.dry_run ... --json                    # print the full report as JSON
    python -m scripts.dry_run ... --no-memory               # the same review with memory switched off
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
import uuid

from app.core import llm
from app.core.profile import get_profile
from app.services import compliance, media
from app.services.fixture_sources import SeedSources, load_seed, seed_identity

EXPECTED_VERDICT = {"approved": "pass", "approved_with_changes": "needs_changes", "rejected": "blocked"}


def show(title: str, result: compliance.ReviewResult, usage: llm.TokenUsage, seconds: float, as_json: bool) -> None:
    r = result.report
    print(f"\n=== {title} ===")
    if as_json:
        print(json.dumps(r.model_dump(), indent=2, ensure_ascii=False))
        return
    print(f"decision: {r.decision}   verdict: {r.verdict}   route: {r.route}   confidence: {r.confidence.score} ({r.confidence.band})")
    print(f"route reason: {r.route_reason}")
    print(f"summary: {r.summary}")
    for v in r.violations:
        ref = v.fundamental_key or f"memory {v.memory_id}"
        print(f"  - [{v.materiality}/{v.basis}] {ref}  conf {v.confidence.score}  quote: {v.quote!r}")
        print(f"      {v.explanation}")
        print(f"      fix: {v.fix}")
    if r.passed_checks:
        print("passed: " + "; ".join(f"{p.check}" for p in r.passed_checks))
    if r.corrected_copy:
        print(f"corrected copy: {r.corrected_copy}")
    print(f"memories in view: {r.memories_used}")
    print(f"tokens: {usage.as_dict()}  steps: {[(c['step'], c['in'], c['out']) for c in usage.calls]}  time: {seconds:.1f}s")


def run(text: str, ctx: dict, identity, sources, *, use_memory: bool, title: str, as_json: bool, usage: llm.TokenUsage | None = None) -> compliance.ReviewResult:
    usage = usage or llm.TokenUsage()
    started = time.time()
    result = compliance.review(text, ctx, identity, str(uuid.uuid4()), use_memory=use_memory, sources=sources, usage=usage)
    show(title, result, usage, time.time() - started, as_json)
    return result


def ad_context(ad: dict) -> dict:
    return {k: ad.get(k) for k in ("product", "offer_id", "region", "channel", "language", "modality", "budget", "visual_notes", "fine_print_legible")}


def suite(use_memory: bool) -> None:
    """Review every seeded ad and compare with the decision recorded for it.

    Each ad is reviewed without the memory of its own past decision, so the result is not simply
    read back. Internal decisions made after an ad was decided are in view, so an ad approved in
    September can correctly come back stricter today; those are listed as "stricter now".

    Claims are extracted for all ads first and their search text embedded in a single request,
    which keeps the whole suite inside a three-requests-a-minute embedding limit.
    """
    from app.core import embeddings

    ads = load_seed("campaigns")
    usage = llm.TokenUsage()
    started = time.time()
    extractions = {ad["ref"]: compliance.extract_claims(ad["text"], ad_context(ad), usage=usage) for ad in ads}
    embeddings.embed_queries([q for ad in ads for q in [ad["text"]] + [c.quote for c in extractions[ad["ref"]].claims]])
    order = ["pass", "needs_changes", "blocked"]
    rows, same, stricter, looser = [], 0, 0, 0
    for ad in ads:
        identity = seed_identity(ad["created_by"])
        sources = SeedSources(exclude_memory_refs={f"decision-{ad['ref']}"})
        result = compliance.review(ad["text"], ad_context(ad), identity, str(uuid.uuid4()), use_memory=use_memory, sources=sources, usage=usage, extraction=extractions[ad["ref"]])
        r = result.report
        recorded = (ad.get("expected") or {}).get("status") or {"pass": "approved", "needs_changes": "approved_with_changes", "blocked": "rejected"}[ad["compliance"]["verdict"]]
        expected = EXPECTED_VERDICT[recorded]
        mark = "same" if r.verdict == expected else "STRICTER" if order.index(r.verdict) > order.index(expected) else "LOOSER"
        same, stricter, looser = same + (mark == "same"), stricter + (mark == "STRICTER"), looser + (mark == "LOOSER")
        cited = sorted({v.fundamental_key or f"mem:{v.memory_id}" for v in r.violations})
        rows.append((mark, ad["ref"], recorded, r.decision, r.confidence.score, ", ".join(cited), ", ".join((ad.get("expected") or {}).get("rules", []))))
    print(f"\n{'':8}  {'ad':8} {'recorded':22} {'now':22} conf  cited now   |   rules recorded")
    for mark, ref, recorded, got, score, cited, rules in rows:
        print(f"{mark:8}  {ref:8} {recorded:22} {got:22} {score:>4}  {cited}   |   {rules}")
    print(f"\n{same} same, {stricter} stricter now, {looser} looser, of {len(ads)}. tokens: {usage.as_dict()}  time: {time.time() - started:.0f}s")


def main() -> None:
    profile = get_profile()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", action="store_true", help="review every seeded ad and compare with its recorded decision")
    p.add_argument("--ad", help="ref of a seeded ad in backend/seed/campaigns.json")
    p.add_argument("--text", help="ad copy to review")
    p.add_argument("--image", help="path to an image ad to read and review")
    p.add_argument("--offer", default=None)
    p.add_argument("--region", default=profile["region"])
    p.add_argument("--channel", default="unspecified")
    p.add_argument("--language", default=None)
    p.add_argument("--as", dest="email", default=None, help="seeded user to act as")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.suite:
        suite(use_memory=not args.no_memory)
        return
    users = load_seed("users")
    default_user = next(u["email"] for u in users if u["role"] == "marketer")
    if args.ad:
        ad = next(a for a in load_seed("campaigns") if a["ref"] == args.ad)
        sources = SeedSources(exclude_memory_refs={f"decision-{ad['ref']}"})
        run(ad["text"], ad_context(ad), seed_identity(args.email or ad["created_by"]), sources, use_memory=not args.no_memory, title=f"seeded ad {args.ad}", as_json=args.json)
        return

    identity = seed_identity(args.email or default_user)
    ctx = {"product": profile["product"], "offer_id": args.offer, "region": args.region, "channel": args.channel, "language": args.language, "modality": "text"}
    usage = llm.TokenUsage()
    text = args.text
    if args.image:
        path = pathlib.Path(args.image)
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        reading = media.read_image_bytes(path.read_bytes(), mime, usage=usage)
        text = reading["text"]
        ctx.update(modality="image", visual_notes=reading["visual_notes"], fine_print_legible=reading["fine_print_legible"])
        print(f"read from image: {text}\nnotes: {reading['visual_notes']}\ndisclaimer easy to read: {reading['fine_print_legible']}")
    if not text:
        p.error("give --suite, --ad, --text or --image")
    run(text, ctx, identity, SeedSources(), use_memory=not args.no_memory, title=args.image or "submitted ad", as_json=args.json, usage=usage)


if __name__ == "__main__":
    main()
