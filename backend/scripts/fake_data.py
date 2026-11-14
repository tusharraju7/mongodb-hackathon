"""Create a database and load the fictional seed data into it, so the backend can be tested on Atlas.

    python -m scripts.fake_data --db greenlight_test --password <any test password>
    python -m scripts.fake_data --db greenlight_test --password <...> --no-media     # skip audio and banners

It follows docs/MONGODB_SETUP.md: the validators and vector index definitions are read straight out
of that file, so the database it builds is the one the docs describe. Everything is upserted on a
natural key, so it is safe to run again.

It refuses to touch the shared `greenlight` database unless --shared is given. That database
belongs to the data owner.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from pymongo.operations import SearchIndexModel

from app.core import embeddings, security
from app.core.config import REPO_ROOT, SEED_DIR
from app.core.db import get_client
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
    ("ledger", [("run_id", 1), ("ts", 1)], {}),
    ("ledger", [("actor.user_id", 1), ("ts", -1)], {}),
    ("runs", [("actor.user_id", 1), ("started_at", -1)], {}),
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def seed(name: str) -> list[dict]:
    return json.loads((SEED_DIR / f"{name}.json").read_text())


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
    while time.time() < deadline:
        state = {name: next((i.get("queryable") for i in db[coll].list_search_indexes() if i["name"] == name), False) for name, (coll, _) in vectors.items()}
        if all(state.values()):
            print("vector indexes: all queryable")
            return True
        time.sleep(5)
    print("vector indexes: still building:", state)
    return False


def load(db, password: str, with_media: bool) -> None:
    at = now()
    for doc in seed("policies"):
        db.policies.replace_one({"_id": doc["_id"]}, {**doc, "updated_at": at}, upsert=True)

    password_hash = security.hash_password(password)
    for u in seed("users"):
        db.users.update_one({"email": u["email"]}, {"$set": {**u, "password_hash": password_hash}, "$setOnInsert": {"created_at": at}}, upsert=True)
    ids = {u["email"]: str(u["_id"]) for u in db.users.find({}, {"email": 1})}

    for o in seed("offers"):
        db.offers.replace_one({"_id": o["_id"]}, {**o, "valid_from": date(o["valid_from"]), "valid_to": date(o["valid_to"])}, upsert=True)

    clauses, ads, memories = seed("fundamentals"), seed("campaigns"), seed("memories")
    # One embedding request for everything that is stored and searched.
    texts = [fundamentals.clause_document(c) for c in clauses] + [campaigns.search_document(a["description"], a["summary"]) for a in ads] + [m["text"] for m in memories]
    vectors = embeddings.embed_documents(texts)
    clause_vecs, ad_vecs, memory_vecs = vectors[: len(clauses)], vectors[len(clauses) : len(clauses) + len(ads)], vectors[len(clauses) + len(ads) :]

    manager = ids["manager.national@tamarack.test"]
    for c, vector in zip(clauses, clause_vecs):
        previous = c.pop("previous_texts", [])
        doc = {**c, "effective_from": date(c["effective_from"]), "effective_to": date(c.get("effective_to")), "embedding": vector, "updated_by": manager, "updated_at": at}
        db.fundamentals.replace_one({"key": c["key"]}, doc, upsert=True)
        stored = db.fundamentals.find_one({"key": c["key"]}, {"_id": 1})
        for n, old_text in enumerate(previous, start=1):
            db.fundamentals_versions.update_one(
                {"key": c["key"], "version": n},
                {"$setOnInsert": {"fundamental_id": stored["_id"], "key": c["key"], "version": n, "snapshot": {**{k: v for k, v in c.items()}, "text": old_text, "version": n}, "replaced_by": manager, "replaced_at": at, "reason": "seed"}},
                upsert=True,
            )

    for a, vector in zip(ads, ad_vecs):
        existing = db.campaigns.find_one({"ref": a["ref"]}, {"assets": 1})
        assets = (existing or {}).get("assets") or []
        if with_media and not assets and a["modality"] in ("audio", "image"):
            meta = {"team": a["team"], "uploaded_by": ids[a["created_by"]]}
            if a["modality"] == "audio":
                data, mime, name = media.synthesize_bytes(a["text"], a["language"]), "audio/mpeg", f"{a['ref']}.mp3"
            else:
                card = "Carte Remises Tamarack" if a["language"] == "fr" else "Tamarack Cashback Card"
                data, mime, name = media.render_image_bytes(a["text"].replace(f"{card}. ", ""), language=a["language"], card_name=card), "image/png", f"{a['ref']}.png"
            file_id = str(media.bucket_for(db).upload_from_stream(name, data, metadata={"mime": mime, **meta}))
            assets = [{"type": a["modality"], "file_id": file_id, "mime": mime}]

        applicable = fundamentals.applicable(regions_for(a["region"]), a["product"], db)
        checked = [{"key": c["key"], "version": c["version"]} for c in applicable]
        offer = db.offers.find_one({"_id": a["offer_id"]})
        verdict, route = a["compliance"]["verdict"], a["compliance"]["route"]
        doc = {
            **{k: a[k] for k in ("ref", "team", "name", "product", "offer_id", "region", "channel", "language", "modality", "budget", "text", "description", "summary", "facts", "status")},
            "visual_notes": a.get("visual_notes"), "version": 1, "history": [], "assets": assets, "source": "seed",
            "compliance": {
                "verdict": verdict, "route": route, "route_reason": "Seeded example", "summary": a["summary"],
                "confidence": {"score": 100, "band": "high", "reasons": ["Seeded example"]},
                "passed_checks": [], "violations": [], "corrected_copy": None, "missing_inputs": [],
                "checked_fundamentals": checked, "offer_version": offer["version"], "memories_used": [], "cached": False, "checked_at": at,
            },
            "embedding": vector, "created_by": ids[a["created_by"]], "created_at": at, "run_id": f"seed-{a['ref']}",
        }
        if a.get("review_feedback"):
            doc["review_feedback"], doc["rejected_by"] = a["review_feedback"], ids[a["rejected_by"]]
        if a["status"] in ("approved", "released"):
            approver = ids[a["approved_by"]]
            doc["approval"] = {"by": approver, "at": at, "ad_version": 1, "policy_versions": checked, "offer_version": offer["version"], "memories": [], "run_id": f"seed-{a['ref']}"}
            if a["status"] == "released":
                doc["released_at"], doc["released_by"] = at, approver
        db.campaigns.replace_one({"ref": a["ref"]}, doc, upsert=True)
        if "approval" in doc and not db.ledger.count_documents({"run_id": f"seed-{a['ref']}"}, limit=1):
            user = db.users.find_one({"email": a["approved_by"]})
            actor = {"user_id": str(user["_id"]), "email": user["email"], "role": user["role"], "team": user["team"]}
            steps = ["campaign.approve"] + (["campaign.release"] if a["status"] == "released" else [])
            for action in steps:
                base = {"run_id": f"seed-{a['ref']}", "thread_id": None, "actor": actor, "action": action, "auth": {"method": "jwt"}}
                db.ledger.insert_one({**base, "ts": now(), "event": "decision", "decision": "allow", "reason": f"role manager holds {action}", "params": {"campaign_ref": a["ref"], "ad_version": 1, "seeded": True}})
                db.ledger.insert_one({**base, "ts": now(), "event": "outcome", "policy_refs": checked, "result": {"status": "ok", "summary": f"Seeded: {action} of '{a['name']}'"}})

    for m, vector in zip(memories, memory_vecs):
        ttl = timedelta(days=m["ttl_days"]) if m.get("ttl_days") else timedelta(minutes=m["ttl_minutes"]) if m.get("ttl_minutes") else None
        doc = {
            "ref": m["ref"], "kind": m["kind"], "text": m["text"],
            "scope": {"team": m["team"], "user_id": ids[m["user_email"]] if m.get("user_email") else None},
            "visibility_roles": m["visibility_roles"], "embedding": vector, "status": "active", "supersedes": None,
            "expires_at": at + ttl if ttl else None, "source": {"type": m["source_type"], "run_id": "seed"},
            "created_by": ids[m["created_by"]], "created_at": at, "use_count": 0, "last_used_at": None,
        }
        db.memories.replace_one({"ref": m["ref"]}, doc, upsert=True)

    counts = {n: db[n].count_documents({}) for n in ("policies", "users", "offers", "fundamentals", "fundamentals_versions", "campaigns", "memories", "ledger")}
    print("loaded:", counts, "| files:", db["fs.files"].count_documents({}))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True)
    p.add_argument("--password", required=True, help="password given to every seeded user")
    p.add_argument("--no-media", action="store_true", help="do not produce the seeded audio and banners")
    p.add_argument("--shared", action="store_true", help="allow writing to the shared `greenlight` database")
    args = p.parse_args()
    if args.db == "greenlight" and not args.shared:
        print("Refusing to write to the shared `greenlight` database without --shared. Use a scratch name such as greenlight_test.")
        return 2
    db = get_client()[args.db]
    print(f"target database: {args.db}")
    setup(db)
    load(db, args.password, with_media=not args.no_media)
    return 0 if wait_for_vectors(db) else 1


if __name__ == "__main__":
    sys.exit(main())
