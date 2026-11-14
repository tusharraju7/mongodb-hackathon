"""Create the database and load the seed data into it.

    python -m scripts.build_seed                                              # northplay-demo-data/ -> backend/seed/
    python -m scripts.load_db --db greenlight --shared --password <password>  # the shared database
    python -m scripts.load_db --db greenlight_scratch --password <password>   # a scratch copy
    python -m scripts.load_db --db greenlight --shared --setup-only           # validators, indexes and rules only

It follows docs/MONGODB_SETUP.md: the validators and vector index definitions are read straight out
of that file, so the database it builds is the one the docs describe. Everything is upserted on a
natural key, so it is safe to run again.

It refuses to touch the shared `greenlight` database unless --shared is given.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from pymongo.operations import SearchIndexModel

from app.core import embeddings, gate, security
from app.core.config import REPO_ROOT, SEED_DIR, SOURCE_DATA_DIR
from app.core.db import get_client
from app.core.profile import get_profile
from app.models import regions_for
from app.services import campaigns, fundamentals, media

DOC = REPO_ROOT / "docs" / "MONGODB_SETUP.md"
INDEXES = [
    ("users", [("email", 1)], {"unique": True}),
    ("fundamentals", [("key", 1)], {"unique": True}),
    ("fundamentals", [("claim_types", 1), ("status", 1)], {}),
    ("fundamentals_versions", [("key", 1), ("version", -1)], {}),
    ("campaigns", [("team", 1), ("status", 1), ("created_at", -1)], {}),
    ("campaigns", [("ref", 1)], {"unique": True, "sparse": True}),
    ("memories", [("expires_at", 1)], {"expireAfterSeconds": 0}),
    ("memories", [("scope.team", 1), ("status", 1), ("kind", 1)], {}),
    ("memories", [("ref", 1)], {"unique": True, "sparse": True}),
    ("ledger", [("run_id", 1), ("ts", 1)], {}),
    ("ledger", [("actor.user_id", 1), ("ts", -1)], {}),
    ("runs", [("actor.user_id", 1), ("started_at", -1)], {}),
    ("runs", [("status", 1), ("heartbeat_at", 1)], {}),
    # One event per position in a run: two writers can never fork the hash chain. Events from before
    # chaining, and seeded ones, have no `seq` and are left out of the index.
    ("ledger", [("run_id", 1), ("seq", 1)], {"unique": True, "partialFilterExpression": {"seq": {"$exists": True}}}),
    ("slack_messages", [("channel", 1), ("ts", 1)], {}),
]
ROUTE_REASON = {"pass": "No findings", "needs_changes": "Changes required before it can run", "blocked": "Material finding"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def date(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def seed(name: str) -> list:
    path = SEED_DIR / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else []


def from_doc() -> tuple[dict, dict]:
    """Validators and vector index definitions, taken from the setup document itself."""
    text = DOC.read_text()
    validators = {m.group(1): (m.group(2), json.loads(m.group(3))) for m in re.finditer(r"\*\*`(\w+)`\*\* \((strict|warn)\)\n```json\n(.*?)```", text, re.S)}
    vectors = {m.group(1): (m.group(2), json.loads(m.group(3))) for m in re.finditer(r"\*\*`(\w+_vec)`\*\* on `(\w+)`\n```json\n(.*?)```", text, re.S)}
    return validators, vectors


def setup(db) -> None:
    validators, vectors = from_doc()
    existing = set(db.list_collection_names())
    for name, (mode, schema) in validators.items():
        options = {"validator": {"$jsonSchema": schema}, "validationLevel": "strict", "validationAction": "error" if mode == "strict" else "warn"}
        if name in existing:
            db.command("collMod", name, **options)
        else:
            db.create_collection(name, **options)
    print(f"collections: {len(validators)} with validators ({sum(m == 'strict' for m, _ in validators.values())} strict)")
    for collection, keys, options in INDEXES:
        db[collection].create_index(keys, **options)
    print(f"indexes: {len(INDEXES)} regular")
    for name, (collection, definition) in vectors.items():
        if name not in {i["name"] for i in db[collection].list_search_indexes()}:
            db[collection].create_search_index(SearchIndexModel(name=name, type="vectorSearch", definition=definition))
    print(f"vector indexes: {len(vectors)} requested")


def wait_for_vectors(db, timeout: int = 300) -> bool:
    _, vectors = from_doc()
    deadline = time.time() + timeout
    state = {}
    while time.time() < deadline:
        state = {name: next((i.get("queryable") for i in db[coll].list_search_indexes() if i["name"] == name), False) for name, (coll, _) in vectors.items()}
        if all(state.values()):
            print("vector indexes: all queryable")
            return True
        time.sleep(5)
    print("vector indexes: still building:", state)
    return False


def load_rules(db) -> None:
    """Who may do what: the role lists, and the rule for each action. Touches no other data."""
    at = now()
    for doc in seed("policies"):
        db.policies.replace_one({"_id": doc["_id"]}, {**doc, "updated_at": at}, upsert=True)
    # The rule for each action, as data. These are the defaults the gate would use anyway; storing
    # them makes them readable in Atlas, and editing one there changes the rule without a deploy.
    for action, rule in gate.DEFAULT_RULES.items():
        db.action_rules.replace_one({"_id": action}, {"_id": action, **rule, "updated_at": at}, upsert=True)
    db.action_rules.replace_one({"_id": "_limits"}, {"_id": "_limits", "per_run": gate.DEFAULT_LIMITS, "note": "The most one run may use before its next step is refused.", "updated_at": at}, upsert=True)
    print("rules:", {"policies": db.policies.count_documents({}), "action_rules": db.action_rules.count_documents({})})


def load(db, password: str, with_media: bool) -> None:
    at = now()
    labels = get_profile()["decision_labels"]
    load_rules(db)

    password_hash = security.hash_password(password)
    for u in seed("users"):
        db.users.update_one({"email": u["email"]}, {"$set": {**u, "password_hash": password_hash}, "$setOnInsert": {"created_at": at}}, upsert=True)
    ids = {u["email"]: str(u["_id"]) for u in db.users.find({}, {"email": 1})}
    people = {u["email"]: u for u in db.users.find({})}

    for o in seed("offers"):
        db.offers.replace_one({"_id": o["_id"]}, {**o, "valid_from": date(o["valid_from"]), "valid_to": date(o["valid_to"])}, upsert=True)

    clauses, ads, memories = seed("fundamentals"), seed("campaigns"), seed("memories")
    # One embedding request for everything that is stored and searched.
    texts = [fundamentals.clause_document(c) for c in clauses] + [campaigns.search_document(a["description"], a["summary"]) for a in ads] + [m["text"] for m in memories]
    # Vectors already computed for the dry run are reused from backend/.cache, which keeps a reload
    # inside the embedding service's rate limit.
    from app.services.fixture_sources import embed_with_disk_cache

    vectors = embed_with_disk_cache(texts)
    clause_vecs, ad_vecs, memory_vecs = vectors[: len(clauses)], vectors[len(clauses) : len(clauses) + len(ads)], vectors[len(clauses) + len(ads) :]

    manager = next(ids[u["email"]] for u in seed("users") if u["role"] == "manager")
    for c, vector in zip(clauses, clause_vecs):
        previous = c.pop("previous_texts", [])
        doc = {**c, "effective_from": date(c["effective_from"]), "effective_to": date(c.get("effective_to")), "embedding": vector, "updated_by": manager, "updated_at": at}
        db.fundamentals.replace_one({"key": c["key"]}, doc, upsert=True)
        stored = db.fundamentals.find_one({"key": c["key"]}, {"_id": 1})
        for n, old_text in enumerate(previous, start=1):
            db.fundamentals_versions.update_one(
                {"key": c["key"], "version": n},
                {"$setOnInsert": {"fundamental_id": stored["_id"], "key": c["key"], "version": n, "snapshot": {**c, "text": old_text, "version": n}, "replaced_by": manager, "replaced_at": at, "reason": "seed"}},
                upsert=True,
            )

    for a, vector in zip(ads, ad_vecs):
        existing = db.campaigns.find_one({"ref": a["ref"]}, {"assets": 1})
        assets = (existing or {}).get("assets") or []
        if with_media and not assets and a.get("asset_path"):
            path = SOURCE_DATA_DIR / a["asset_path"]
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            file_id = str(media.bucket_for(db).upload_from_stream(path.name, path.read_bytes(), metadata={"mime": mime, "team": a["team"], "uploaded_by": ids[a["created_by"]], "source": a["asset_path"]}))
            assets = [{"type": "image", "file_id": file_id, "mime": mime}]

        applicable = fundamentals.applicable(regions_for(a["region"]), a["product"], db)
        checked = [{"key": c["key"], "version": c["version"]} for c in applicable]
        offer = db.offers.find_one({"_id": a["offer_id"]}) if a.get("offer_id") else None
        comp = a["compliance"]
        decided = date(a.get("decided_at")) or at
        score = int(comp.get("confidence", 100))
        doc = {
            **{k: a.get(k) for k in ("ref", "team", "name", "product", "offer_id", "region", "channel", "language", "modality", "budget", "text", "description", "summary", "facts", "status", "campaign")},
            "visual_notes": a.get("visual_notes"), "fine_print_legible": a.get("fine_print_legible"),
            "version": 1, "history": [], "assets": assets, "source": "seed",
            "compliance": {
                "verdict": comp["verdict"], "decision": labels.get(comp["verdict"]), "route": comp["route"], "route_reason": ROUTE_REASON[comp["verdict"]],
                "summary": comp.get("summary") or a["summary"],
                "confidence": {"score": score, "band": "high" if score >= 80 else "medium" if score >= 50 else "low", "reasons": ["Recorded decision"]},
                "passed_checks": [], "violations": comp.get("violations", []), "corrected_copy": comp.get("corrected_copy"), "missing_inputs": [],
                "checked_fundamentals": checked, "offer_version": offer["version"] if offer else None, "memories_used": [], "cached": False, "checked_at": decided,
            },
            "embedding": vector, "created_by": ids[a["created_by"]], "created_at": decided, "run_id": f"seed-{a['ref']}",
        }
        if a.get("review_feedback"):
            doc["review_feedback"], doc["rejected_by"] = a["review_feedback"], ids[a["rejected_by"]]
        if a["status"] in ("approved", "released"):
            approver = ids[a["approved_by"]]
            doc["approval"] = {"by": approver, "at": decided, "ad_version": 1, "policy_versions": checked, "offer_version": offer["version"] if offer else None, "memories": [], "run_id": f"seed-{a['ref']}"}
            if a["status"] == "released":
                doc["released_at"], doc["released_by"] = decided, approver
        db.campaigns.replace_one({"ref": a["ref"]}, doc, upsert=True)
        if "approval" in doc and not db.ledger.count_documents({"run_id": f"seed-{a['ref']}"}, limit=1):
            user = people[a["approved_by"]]
            actor = {"user_id": str(user["_id"]), "email": user["email"], "role": user["role"], "team": user["team"]}
            for action in ["campaign.approve"] + (["campaign.release"] if a["status"] == "released" else []):
                base = {"run_id": f"seed-{a['ref']}", "thread_id": None, "actor": actor, "action": action, "auth": {"method": "jwt"}}
                db.ledger.insert_one({**base, "ts": decided, "event": "decision", "decision": "allow", "reason": f"role manager holds {action}", "params": {"campaign_ref": a["ref"], "ad_version": 1, "seeded": True}})
                db.ledger.insert_one({**base, "ts": decided, "event": "outcome", "policy_refs": checked, "result": {"status": "ok", "summary": f"Recorded: {action} of '{a['name']}'"}})

    for m, vector in zip(memories, memory_vecs):
        ttl = timedelta(days=m["ttl_days"]) if m.get("ttl_days") else timedelta(minutes=m["ttl_minutes"]) if m.get("ttl_minutes") else None
        source = {**(m.get("source") or {"type": m["source_type"]}), "run_id": "seed"}
        happened = date(source.get("date")) or at
        doc = {
            "ref": m["ref"], "kind": m["kind"], "text": m["text"], "authority": m.get("authority"), "materiality": m.get("materiality"),
            "scope": {"team": m["team"], "user_id": ids[m["user_email"]] if m.get("user_email") else None},
            "visibility_roles": m["visibility_roles"], "embedding": vector, "status": "active", "supersedes": None,
            "expires_at": at + ttl if ttl else None, "source": source,
            "created_by": ids[m["created_by"]], "created_at": happened, "use_count": 0, "last_used_at": None,
        }
        db.memories.replace_one({"ref": m["ref"]}, doc, upsert=True)

    # The records the memories and clauses were built from, kept as they were, so every memory can be traced to its source.
    raw = {
        "slack_messages": (seed("raw_slack_messages"), lambda d: {"channel": d["channel"], "ts": d["ts"]}),
        "strategy_docs": (seed("raw_strategy_docs"), lambda d: {"title": d["title"]}),
    }
    source_dir = SOURCE_DATA_DIR
    if (source_dir / "regulations" / "regulations.json").exists():
        raw["regulations"] = (json.loads((source_dir / "regulations" / "regulations.json").read_text()), lambda d: {"rule_id": d["rule_id"]})
        raw["ad_decisions"] = (json.loads((source_dir / "historical_ads" / "historical_ads.json").read_text()), lambda d: {"ad_id": d["ad_id"]})
    for name, (docs, key) in raw.items():
        for d in docs:
            db[name].replace_one(key(d), d, upsert=True)

    names = ("action_rules", "policies", "users", "offers", "fundamentals", "fundamentals_versions", "campaigns", "memories", "ledger", "slack_messages", "strategy_docs", "regulations", "ad_decisions")
    print("loaded:", {n: db[n].count_documents({}) for n in names}, "| files:", db["fs.files"].count_documents({}))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True)
    p.add_argument("--password", default="", help="password given to every seeded user (not needed with --setup-only)")
    p.add_argument("--no-media", action="store_true", help="do not upload the past ads' images")
    p.add_argument("--shared", action="store_true", help="allow writing to the shared `greenlight` database")
    p.add_argument("--setup-only", action="store_true", help="apply validators, indexes and the action rules only; leave users, ads, memories and files as they are")
    args = p.parse_args()
    if args.db == "greenlight" and not args.shared:
        print("Refusing to write to the shared `greenlight` database without --shared. Use a scratch name such as greenlight_scratch.")
        return 2
    if not args.setup_only and not args.password:
        print("--password is required unless --setup-only is given.")
        return 2
    db = get_client()[args.db]
    print(f"target database: {args.db}  |  data set: {get_profile()['brand']}")
    setup(db)
    if args.setup_only:
        load_rules(db)
        return 0
    load(db, args.password, with_media=not args.no_media)
    return 0 if wait_for_vectors(db) else 1


if __name__ == "__main__":
    sys.exit(main())
