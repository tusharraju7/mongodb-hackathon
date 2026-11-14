"""Turn northplay-demo-data/ into the seed files the backend loads (backend/seed/*.json).

    python -m scripts.build_seed                # regenerate the seed files
    python -m scripts.build_seed --read-images  # also read the 15 past ads' images (15 model calls, cached)

Mapping:
  regulations/regulations.json   -> fundamentals.json   (policy clauses)
  historical_ads/                -> campaigns.json      (the ad library) and past-verdict memories
  slack/slack_export/            -> memories.json       (one memory per channel per day, with its standing)
  strategy_decks/*.md            -> memories.json       (one background memory per slide)

Nothing in demo_ads/ is read: those three are uploaded live.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone

from app.core.config import BACKEND_ROOT, SOURCE_DATA_DIR

OUT = BACKEND_ROOT / "seed"
SRC = SOURCE_DATA_DIR
TEAM, REGION, PRODUCT = "ontario", "CA-ON", "sportsbook"
HOUSE_DISCLAIMER = "19+. Ontario only. Please play responsibly. Concerned about your gambling? Contact ConnexOntario 1-866-531-2600."

PROFILE = {
    "brand": "NorthPlay",
    "description": "NorthPlay, an online sportsbook licensed in Ontario, Canada",
    "product": PRODUCT, "region": REGION, "teams": ["ontario", "alberta"],
    "claim_types": {
        "inducement": "a bonus, bonus bet, deposit match, odds boost, credit, cash back, promo code, or any amount tied to an offer",
        "free_or_risk_free": "the words free, risk-free, no risk or on us, or any promise that the player cannot lose money",
        "odds_or_certainty": "a statement about odds, the chance of winning, or certainty of an outcome (lock, sure thing, guaranteed, can't lose, easy money)",
        "endorsement": "a person or character who is named, quoted or pictured: an athlete, celebrity, influencer or mascot",
        "income_or_problem_solving": "gambling presented as income, an investment, or a way to pay bills or fix money or personal problems",
        "loss_chasing": "encouragement to win back losses or to keep betting after losing",
        "status_or_peer": "gambling linked to status, attractiveness, success, coming of age, or pressure from friends",
        "trademark_or_league": "a league, event, team name, logo or other mark the company may not hold rights to",
    },
    "memory": {"per_query": 6, "budget": 12, "quotas": {"binding": 5, "guidance": 2, "precedent": 3, "background": 2}},
    "banner": {"header": "NORTHPLAY", "background": [11, 37, 54], "text": [240, 246, 244], "accent": [120, 222, 190], "headline": "first"},
    "fine_print_patterns": [r"19\+", "ontario only", "play responsibly", "connexontario"],
    "decision_labels": {"pass": "approved", "needs_changes": "approved_with_changes", "blocked": "rejected"},
    # Domain notes given to the reviewer. They restate the regulations in plain words; they never encode
    # an internal decision, which must reach the review through memory so that it can be traced and changed.
    "guidance": [
        "Channels come in three classes. Public: paid social, programmatic display, video platforms, TV, radio, podcasts, outdoor and search. Owned: the company's own site and app. Direct: email, SMS and push to players who have actively opted in.",
        "An inducement is any bonus, bonus bet, deposit match, odds boost, credit, cash back or promo code, or any dollar amount tied to an offer. Inducements themselves are legal; advertising them is allowed only on owned channels and in direct marketing to opted-in players.",
        "The legal age is 19. A person who is or looks under 19, and anything that would appeal mainly to people under 19, is a problem wherever it appears.",
        "Showing odds as facts is allowed. Suggesting that a win is certain, likely or easy is not.",
        "An active or retired athlete may appear only in a message whose sole purpose is responsible gambling, with no call to bet.",
        "Every ad must carry a responsible gambling message and '19+'. That is checked automatically, so do not report it yourself.",
    ],
    "channel_classes": {
        "direct": ["email", "sms", "push", "opted-in", "opted in", "direct marketing"],
        "owned": ["on-site", "onsite", "website", "in-app", "app banner", "own site"],
        "public": ["social", "instagram", "facebook", "tiktok", "snapchat", "youtube", "display", "programmatic", "tv", "radio", "podcast", "billboard", "outdoor", "search", "x (", "twitter"],
    },
}

# Clauses tied to a kind of claim. The rest apply to every ad.
CLAIM_TYPES = {
    "REG-02": ["endorsement"], "REG-03": ["endorsement"], "REG-07": ["income_or_problem_solving"], "REG-08": ["loss_chasing"],
    "REG-09": ["odds_or_certainty"], "REG-11": ["status_or_peer"], "REG-12": ["inducement"], "REG-13": ["free_or_risk_free", "inducement"],
}
CATEGORY = {
    "Protection of Minors": "minors", "Responsible Gambling": "responsible_gambling", "Truthful Advertising": "truthful_advertising",
    "Inducements": "inducements", "Required Disclosures": "required_disclosures", "Targeting & Consent": "targeting_consent",
}
MATERIALITY = {"blocker": "material", "major": "disclosure", "minor": "formatting"}

# The people in the Slack export who can log in, plus three fictional additions so that every role
# and a second team exist. Managers are the ones whose decisions are binding.
USERS = [
    {"email": "ethan.cho@northplay.test", "name": "Ethan Cho", "title": "Senior Counsel, Legal & Compliance", "role": "manager", "team": "ontario", "slack_id": "U03EC"},
    {"email": "priya.nair@northplay.test", "name": "Priya Nair", "title": "Chief Marketing Officer", "role": "manager", "team": "ontario", "slack_id": "U02PN"},
    {"email": "amira.haddad@northplay.test", "name": "Amira Haddad", "title": "Creative Lead", "role": "marketer", "team": "ontario", "slack_id": "U06AH"},
    {"email": "kevin.tran@northplay.test", "name": "Kevin Tran", "title": "Growth Marketing Manager", "role": "marketer", "team": "ontario", "slack_id": "U07KT"},
    {"email": "jordan.blake@northplay.test", "name": "Jordan Blake", "title": "Player Support Lead (added for the demo)", "role": "sales", "team": "ontario"},
    {"email": "manager.alberta@northplay.test", "name": "Morgan Reid", "title": "Counsel, Alberta launch (added for the demo)", "role": "manager", "team": "alberta"},
    {"email": "marketer.alberta@northplay.test", "name": "Sam Okoye", "title": "Marketing, Alberta launch (added for the demo)", "role": "marketer", "team": "alberta"},
]
BINDING_TITLES = ("CEO", "Chief Marketing Officer", "Senior Counsel")
DECISION_WORDS = re.compile(r"(\bdecision\b|effective (today|immediately)|\bdo not\b|\bdon't\b|\bnever\b|\bpaus(ed|ing)\b|\bterminated\b|\bretired\b|off-limits|off-brand|can't run|not without|no mascots|overrid|\d+px minimum)", re.I)
VERDICT = {"approved": ("pass", "none", "released"), "rejected": ("blocked", "human_review", "rejected"), "approved_with_changes": ("needs_changes", "draft_correction", "pending_review")}


def write(name: str, data) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def clauses() -> list[dict]:
    out = []
    for r in json.loads((SRC / "regulations" / "regulations.json").read_text()):
        key = r["rule_id"]
        checks = r["check_for"] if isinstance(r["check_for"], list) else [r["check_for"]]
        clause = {
            "key": key, "category": CATEGORY.get(r["category"], "other"), "region": REGION, "product": PRODUCT,
            "title": r["title"],
            "text": f"{r['rule']}\nWhat to check: {'; '.join(checks)}.\nHow to fix: {r['remediation']}",
            "summary": r["rule"], "source_section": r["source"],
            "claim_types": CLAIM_TYPES.get(key, []), "materiality": MATERIALITY.get(r["severity"], "material"), "severity": r["severity"],
            "status": "approved", "effective_from": "2026-01-01T00:00:00Z", "effective_to": None, "version": 1,
        }
        if key == "REG-14":
            clause["approved_fix"] = {"en": HOUSE_DISCLAIMER}
            clause["rule"] = {"type": "required_elements", "elements": [
                {"name": "a responsible gambling message", "any": ["play responsibly", "gamble responsibly", "connexontario", "responsible gambling"]},
                {"name": "the 19+ age statement", "any": ["19+"]},
            ]}
        out.append(clause)
    return out


def ads_and_precedents(by_key: dict, readings: dict) -> tuple[list[dict], list[dict]]:
    ads, memories = [], []
    for a in json.loads((SRC / "historical_ads" / "historical_ads.json").read_text()):
        verdict, route, status = VERDICT[a["status"]]
        cited = [c["rule_id"] for c in a["rules_cited"]]
        violations = [] if verdict == "pass" else [
            {
                "source": "fundamental", "basis": "model", "certainty": "clear", "fundamental_key": c["rule_id"], "version": 1,
                "materiality": by_key[c["rule_id"]]["materiality"], "quote": "", "explanation": c["finding"], "reasoning": c["finding"],
                "evidence": {}, "fix": " ".join(a.get("required_changes") or []),
                "confidence": {"score": round(a["confidence"] * 100), "band": "high", "reasons": ["Recorded decision"]},
            }
            for c in a["rules_cited"]
        ]
        reading = readings.get(a["ad_id"], {})
        title = f"{a['ad_id']} {a['headline']}".strip()
        ads.append({
            "ref": a["ad_id"], "team": TEAM, "name": title, "product": PRODUCT, "offer_id": None, "region": REGION,
            "channel": a["channel"], "language": "en", "modality": "image", "budget": None, "campaign": a["campaign"],
            "text": a["extracted_text"], "visual_notes": reading.get("visual_notes"), "fine_print_legible": reading.get("fine_print_legible"),
            "description": f"{a['headline']} {a['body_copy'] or ''} ({a['campaign']}, {a['channel']})".replace("  ", " "),
            "summary": f"{a['campaign']} ad for {a['channel']}. {a['headline']} {a['body_copy'] or ''}".strip(),
            "facts": {"claims": [], "cta": a.get("cta"), "tone": None, "language": "en", "headline": a["headline"], "odds": a.get("odds")},
            "status": status, "decided_at": f"{a['decision_date']}T16:00:00Z",
            "compliance": {"verdict": verdict, "route": route, "summary": a["rationale"], "violations": violations, "corrected_copy": a.get("revised_copy"), "confidence": round(a["confidence"] * 100)},
            "expected": {"status": a["status"], "rules": cited},
            "created_by": "amira.haddad@northplay.test",
            **({"approved_by": "ethan.cho@northplay.test"} if status == "released" else {}),
            **({"rejected_by": "ethan.cho@northplay.test", "review_feedback": a["rationale"]} if status == "rejected" else {}),
            "asset_path": f"historical_ads/images/{a['file']}",
        })
        findings = "; ".join(f"{c['rule_id']} ({c['finding']})" for c in a["rules_cited"])
        changes = f" Required changes: {' '.join(a['required_changes'])}" if a.get("required_changes") else ""
        memories.append({
            "ref": f"decision-{a['ad_id']}", "kind": "episodic", "authority": "precedent", "team": TEAM, "user_email": None,
            "text": f"Past decision on ad {a['ad_id']} \"{a['headline']}\" ({a['channel']}): {a['status'].replace('_', ' ')}. Rules: {findings}. {a['rationale']}{changes}",
            "visibility_roles": ["manager", "marketer"], "source_type": "agent", "created_by": "ethan.cho@northplay.test",
            "source": {"type": "ad_decision", "ref": a["ad_id"], "date": a["decision_date"]}, "ttl_days": None,
        })
    return ads, memories


def slack_memories() -> tuple[list[dict], list[dict]]:
    root = SRC / "slack" / "slack_export"
    people = {u["id"]: u for u in json.loads((root / "users.json").read_text())}
    logins = {u["slack_id"]: u["email"] for u in USERS if u.get("slack_id")}
    memories, raw = [], []
    for channel in json.loads((root / "channels.json").read_text()):
        name = channel["name"]
        for day in sorted((root / name).glob("*.json")):
            messages = json.loads(day.read_text())
            lines, authors, titles = [], [], []
            for m in messages:
                person = people.get(m["user"], {})
                who, title = person.get("real_name") or m["user"], (person.get("profile") or {}).get("title", "")
                lines.append(f"{who} ({title}): {m['text']}")
                authors.append(who)
                titles.append(title)
                raw.append({"channel": name, "date": day.stem, "ts": m["ts"], "user": m["user"], "author": who, "title": title, "text": m["text"], "reactions": m.get("reactions", [])})
            text = "\n".join(lines)
            decisive = bool(DECISION_WORDS.search(text))
            senior = any(t.startswith(BINDING_TITLES) for t in titles)
            if name == "legal-marketing":
                kind, authority, materiality = "procedural", "binding", "material"
            elif decisive and senior:
                kind, authority, materiality = "procedural", "binding", "material"
            elif decisive:
                kind, authority, materiality = "procedural", "guidance", "disclosure"
            else:
                kind, authority, materiality = "semantic", "background", None
            first = next((u for u in (m["user"] for m in messages) if u in logins), None)
            memories.append({
                "ref": f"slack-{name}-{day.stem}", "kind": kind, "authority": authority, "materiality": materiality, "team": TEAM, "user_email": None,
                "text": f"Slack #{name}, {day.stem}.\n{text}",
                # The leadership channel is confidential: managers only.
                "visibility_roles": ["manager"] if name == "leadership" else ["manager", "marketer"],
                "source_type": "manager_instruction", "created_by": logins.get(first, "ethan.cho@northplay.test"),
                "source": {"type": "slack", "channel": name, "date": day.stem, "authors": list(dict.fromkeys(authors)), "message_ts": [m["ts"] for m in messages]},
                "ttl_days": None,
            })
    return memories, raw


def deck_memories() -> tuple[list[dict], list[dict]]:
    memories, raw = [], []
    for path in sorted((SRC / "strategy_decks").glob("*.md")):
        text = path.read_text()
        title = re.search(r"^# (.+)$", text, re.M).group(1).strip()
        found = re.search(r"(\w+ \d{1,2}, \d{4})", text[:600])
        date = datetime.strptime(found.group(1), "%B %d, %Y").date().isoformat() if found else None
        raw.append({"title": title, "date": date, "file": path.name, "text": text})
        for n, section in enumerate(re.split(r"^## ", text, flags=re.M)[1:], start=1):
            heading, _, body = section.partition("\n")
            memories.append({
                "ref": f"deck-{path.stem.lower()}-{n:02d}", "kind": "semantic", "authority": "background", "materiality": None, "team": TEAM, "user_email": None,
                "text": f"{title}{f' ({date})' if date else ''}, {heading.strip()}.\n{body.strip()}",
                "visibility_roles": ["manager", "marketer"], "source_type": "manager_instruction", "created_by": "priya.nair@northplay.test",
                "source": {"type": "strategy_deck", "title": title, "date": date, "section": heading.strip()}, "ttl_days": None,
            })
    return memories, raw


def read_images(force: bool) -> dict:
    """What a vision model sees in each past ad. Kept in the seed folder so it is done once."""
    cache = OUT / "image_readings.json"
    readings = json.loads(cache.read_text()) if cache.exists() else {}
    from app.services import media

    for a in json.loads((SRC / "historical_ads" / "historical_ads.json").read_text()):
        if a["ad_id"] in readings and not force:
            continue
        data = (SRC / "historical_ads" / "images" / a["file"]).read_bytes()
        r = media.read_image_bytes(data, "image/png")
        readings[a["ad_id"]] = r
        print(f"  read {a['ad_id']}: legible={r['fine_print_legible']} people={r['people_present']}")
        cache.write_text(json.dumps(readings, indent=2, ensure_ascii=False) + "\n")
    return readings


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--read-images", action="store_true")
    p.add_argument("--force", action="store_true", help="read images again even if a reading is cached")
    args = p.parse_args()

    write("profile", PROFILE)
    readings = read_images(args.force) if args.read_images else (json.loads((OUT / "image_readings.json").read_text()) if (OUT / "image_readings.json").exists() else {})
    rules = clauses()
    ads, precedents = ads_and_precedents({c["key"]: c for c in rules}, readings)
    slack, raw_slack = slack_memories()
    decks, raw_decks = deck_memories()
    policies = json.loads((BACKEND_ROOT / "tests" / "fixtures" / "tamarack" / "policies.json").read_text())

    write("users", USERS)
    write("policies", policies)
    write("offers", [])
    write("fundamentals", rules)
    write("campaigns", ads)
    write("memories", slack + decks + precedents)
    write("raw_slack_messages", raw_slack)
    write("raw_strategy_docs", raw_decks)
    standing = {}
    for m in slack + decks + precedents:
        standing[m["authority"]] = standing.get(m["authority"], 0) + 1
    print(f"clauses {len(rules)} | ads {len(ads)} ({sum(a['visual_notes'] is not None for a in ads)} with image readings) | memories {len(slack + decks + precedents)} {standing} | slack messages {len(raw_slack)}")
    print(f"built at {datetime.now(timezone.utc).isoformat(timespec='seconds')} into {OUT}")


if __name__ == "__main__":
    main()
