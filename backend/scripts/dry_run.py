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

# What the data set's README says the three live demo ads should come out as. The detailed answer
# keys are held outside the repo.
DEMO_EXPECTED = [
    ("demo_01_hockey_night_live.png", "approved", "Clean ad"),
    ("demo_02_big_game_bonus.png", "rejected", "Rejected on regulations and on Slack"),
    ("demo_03_play_smart_breaks.png", "rejected", "Passes the regulations and matches an approved precedent; rejected only because of Slack"),
]
DEMO_CHANNEL = "Instagram (paid social)"


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


def suite(use_memory: bool, report_path: str | None = None) -> None:
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
    details: list[dict] = []
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
        details.append({"ref": ad["ref"], "name": ad["name"], "recorded": recorded, "now": r.decision, "mark": mark, "confidence": r.confidence.score,
                        "cited": cited, "recorded_rules": (ad.get("expected") or {}).get("rules", []), "summary": r.summary, "conflicts": len(r.conflicts)})
    print(f"\n{'':8}  {'ad':8} {'recorded':22} {'now':22} conf  cited now   |   rules recorded")
    for mark, ref, recorded, got, score, cited, rules in rows:
        print(f"{mark:8}  {ref:8} {recorded:22} {got:22} {score:>4}  {cited}   |   {rules}")
    seconds = time.time() - started
    print(f"\n{same} same, {stricter} stricter now, {looser} looser, of {len(ads)}. tokens: {usage.as_dict()}  time: {seconds:.0f}s")
    if report_path:
        demo = demo_ads(use_memory)
        write_report(report_path, details, demo, {"same": same, "stricter": stricter, "looser": looser, "seconds": seconds, "tokens": usage.as_dict()})
        print(f"report written to {report_path}")


def demo_ads(use_memory: bool) -> list[dict]:
    """Read and review the three live demo images, with and without memory."""
    from app.core.config import SOURCE_DATA_DIR

    identity = seed_identity(next(u["email"] for u in load_seed("users") if u["role"] == "marketer"))
    profile = get_profile()
    out = []
    for name, expected, story in DEMO_EXPECTED:
        usage = llm.TokenUsage()
        started = time.time()
        reading = media.read_image_bytes((SOURCE_DATA_DIR / "demo_ads" / name).read_bytes(), "image/png", usage=usage)
        ctx = {"product": profile["product"], "region": profile["region"], "channel": DEMO_CHANNEL, "modality": "image",
               "visual_notes": reading["visual_notes"], "fine_print_legible": reading["fine_print_legible"]}
        with_memory = compliance.review(reading["text"], dict(ctx), identity, str(uuid.uuid4()), use_memory=use_memory, sources=SeedSources(), usage=usage).report
        seconds = time.time() - started
        without = compliance.review(reading["text"], dict(ctx), identity, str(uuid.uuid4()), use_memory=False, sources=SeedSources()).report
        out.append({
            "file": name, "expected": expected, "story": story, "now": with_memory.decision, "without_memory": without.decision,
            "confidence": with_memory.confidence.score, "seconds": seconds, "tokens": usage.as_dict(),
            "regulations": sorted({v.fundamental_key for v in with_memory.violations if v.fundamental_key}),
            "memories": sorted({v.memory_id for v in with_memory.violations if v.memory_id}),
            "conflicts": [c["explanation"] for c in with_memory.conflicts], "summary": with_memory.summary,
        })
        print(f"demo {name}: expected {expected}, got {with_memory.decision}; without memory {without.decision}")
    return out


def write_report(path: str, details: list[dict], demo: list[dict], totals: dict) -> None:
    from datetime import datetime, timezone

    from app.agent.prompts import PROMPT_VERSION
    from app.core.config import get_settings

    s = get_settings()
    lines = [
        "# Review results against the expected outcomes",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `python -m scripts.dry_run --suite --report`. "
        f"Prompt version `{PROMPT_VERSION}`; verdict model `{s.llm_model}` at effort `{s.llm_effort}`; fast model `{s.llm_fast_model}`.",
        "",
        "## Where the expected results come from",
        "",
        "- **15 past ads.** `northplay-demo-data/historical_ads/historical_ads.json` records, for each, the decision that was made and the rules it cited. That record is the expected result.",
        "- **3 demo ads.** The data set's README states what each should come out as. The detailed answer keys are held outside the repo.",
        "",
        "Each past ad is reviewed without the memory of its own decision, so the result is not simply read back. Slack decisions made after an ad was decided are in view, so an ad can correctly come back stricter today than it was decided then.",
        "",
        "## The three demo ads",
        "",
        f"Submitted for the channel \"{DEMO_CHANNEL}\", which is an assumption: the channel is chosen at upload.",
        "",
        "| Ad | Expected | Agent | Match | Regulations cited | Slack decisions cited | Without memory | Confidence | Time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in demo:
        ok = "yes" if d["now"] == d["expected"] else "**no**"
        lines.append(f"| `{d['file']}` | {d['expected']} | {d['now']} | {ok} | {', '.join(d['regulations']) or 'none'} | {', '.join(m.replace('slack-', '#') for m in d['memories']) or 'none'} | {d['without_memory']} | {d['confidence']} | {d['seconds']:.0f} s |")
    lines += [""]
    for d in demo:
        lines += [f"**`{d['file']}`** — {d['story']}.", "", f"> {d['summary']}", ""]
        if d["conflicts"]:
            lines += ["Conflicts the agent reported between sources:", ""] + [f"- {c}" for c in d["conflicts"]] + [""]
    lines += [
        "## The 15 past ads",
        "",
        f"**{totals['same']} of {len(details)} match the recorded decision; {totals['stricter']} stricter; {totals['looser']} looser.** "
        f"Whole run: {totals['seconds']:.0f} s, {totals['tokens'].get('in', 0):,} input tokens of which {totals['tokens'].get('cached', 0):,} were served from the prompt cache.",
        "",
        "| Ad | Recorded | Agent | Match | Rules recorded | Cited by the agent | Confidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in details:
        mark = {"same": "yes", "STRICTER": "**stricter**", "LOOSER": "**looser**"}[d["mark"]]
        lines.append(f"| {d['name']} | {d['recorded'].replace('_', ' ')} | {(d['now'] or '').replace('_', ' ')} | {mark} | {', '.join(d['recorded_rules']) or 'none'} | {', '.join(c.replace('mem:slack-', '#') for c in d['cited']) or 'none'} | {d['confidence']} |")
    lines += [
        "",
        "Reading the rule columns: for an approved ad the record lists the rules it was checked against, and the agent cites none because it found no breach. For a rejected ad, the agent's citations should include the recorded ones; extra citations are further breaches it found, and `#channel-date` entries are Slack decisions.",
        "",
        "## Where it differs",
        "",
    ]
    differing = [d for d in details if d["mark"] != "same"]
    lines += [f"- **{d['name']}** — recorded {d['recorded'].replace('_', ' ')}, agent says {(d['now'] or '').replace('_', ' ')}. {d['summary']}" for d in differing] or ["Nothing differs."]
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    profile = get_profile()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", action="store_true", help="review every seeded ad and compare with its recorded decision")
    p.add_argument("--report", nargs="?", const="../docs/RESULTS.md", help="with --suite: also review the three demo ads and write a results page")
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
        suite(use_memory=not args.no_memory, report_path=args.report)
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
