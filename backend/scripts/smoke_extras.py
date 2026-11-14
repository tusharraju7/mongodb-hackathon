"""Live checks beyond scripts/smoke.py: image in and out, the live ledger stream, stop mid-run,
conversation memory, memory expiry, and the collection validators.

    uvicorn app.main:app --port 8000                       # in one terminal
    python -m scripts.smoke_extras [--base URL] [--out DIR]   # in another

Needs the seeded database and SEED_PASSWORD, like smoke.py. Run it a few minutes after seeding so
the five-minute memory has had time to expire. It writes test ads and ledger events.
"""
import argparse, json, pathlib, tempfile, threading, time, uuid
import httpx
from pymongo.errors import WriteError
from app.core.config import get_settings
from app.core.db import get_db
from app.services import media

_p = argparse.ArgumentParser()
_p.add_argument("--base", default="http://localhost:8000")
_p.add_argument("--out", default=tempfile.gettempdir(), help="where to save the regenerated banner for a look")
_args = _p.parse_args()
BASE, PW, OUT = _args.base, get_settings().seed_password, pathlib.Path(_args.out)
RUNNING = "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."
AD = {"product": "credit_card", "offer_id": "TCB-FALL-2026", "region": "CA", "channel": "display", "budget": {"amount": 8000, "currency": "CAD"}}
http = httpx.Client(base_url=BASE, timeout=600)
db = get_db()
ok_count = [0, 0]
def check(ok, what, detail=""):
    ok_count[0 if ok else 1] += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"   [{detail}]" if detail and not ok else ""), flush=True)
def login(name):
    r = http.post("/auth/login", json={"email": f"{name}@tamarack.test", "password": PW}).json()
    return {"Authorization": f"Bearer {r['token']}"}, r["token"]
(mkt, mkt_token), (mgr, _), (sales, sales_token) = login("marketer.national"), login("manager.national"), login("sales.national")

print("Image in and out")
banner = media.render_image_bytes(RUNNING)
up = http.post("/assets", headers=mkt, files={"file": ("bad_banner.png", banner, "image/png")}).json()
check(up.get("type") == "image", "image upload accepted", str(up))
r = http.post("/chat", headers=mkt, json={"thread_id": "img-" + uuid.uuid4().hex, "file_id": up["file_id"], "ad": {**AD, "name": "Extras banner"}}).json()
rep = next(c["data"] for c in r["cards"] if c["type"] == "compliance_report"); ad = next(c["data"] for c in r["cards"] if c["type"] == "campaign")
cited = {v.get("fundamental_key") for v in rep["violations"]}
check(rep["verdict"] == "blocked" and ad["modality"] == "image" and ad["asset"]["type"] == "image", "image ad is read, reviewed and filed with its image", f"{rep['verdict']} {ad['modality']}")
check({"credit.approval_claims", "policy.offer_accuracy"} <= cited, "same findings as the text version", str(sorted(cited)))
mismatch = next(v for v in rep["violations"] if v.get("fundamental_key") == "policy.offer_accuracy")
check(mismatch["confidence"]["score"] == 80 and any("image" in x for x in mismatch["confidence"]["reasons"]), "confidence is lower for an image reading (100 x 0.80)", str(mismatch["confidence"]))
print("     ad text read from the image:", ad["text"][:110])
regen = http.post(f"/campaigns/{ad['id']}/regenerate", headers=mkt, json={}).json()
check(regen.get("status") == "regenerated" and regen["campaign"]["asset"]["type"] == "image" and regen["campaign"]["version"] == 2, "regenerated as a new banner, version 2", str(regen.get("status")))
img = http.get(regen["campaign"]["asset"]["url"] + f"?token={mkt_token}")
check(img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG", "the new banner is served with the token in the query string")
(OUT / "regenerated_banner.png").write_bytes(img.content)
check(http.get(regen["campaign"]["asset"]["url"] + f"?token={sales_token}").status_code == 404, "sales cannot fetch the file of an unreleased ad")
check(http.get(regen["campaign"]["asset"]["url"]).status_code == 401, "no token, no file")
full = http.get(f"/campaigns/{ad['id']}", headers=mkt).json()
check(len(full["history"]) == 1 and full["history"][0]["version"] == 1 and full["derived_from"] == 1, "version 1 is kept in the ad's history")

print("Live ledger stream, and conversation memory")
run_id, thread = str(uuid.uuid4()), "thr-" + uuid.uuid4().hex
seen = []
def follow():
    with httpx.stream("GET", f"{BASE}/audit/stream?run_id={run_id}&token={mkt_token}", timeout=120) as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:]); seen.append((time.time(), e.get("event"), e.get("action"), e.get("decision"), (e.get("params") or {}).get("step")))
            if line.startswith("event: end"): return
t = threading.Thread(target=follow, daemon=True); t.start(); time.sleep(1.5)
started = time.time()
r = http.post("/chat", headers=mkt, json={"thread_id": thread, "run_id": run_id, "ad": {**AD, "channel": "email", "name": "Extras email", "text": "Enjoy 0% interest on purchases for 10 months, then 20.99%. Earn $300 cash back after $1,500 in purchases in your first 3 months. Apply today. Subject to credit approval. Conditions apply. Unsubscribe: tamarack.test/unsubscribe"}}).json()
finished = time.time(); t.join(timeout=15)
first = seen[0] if seen else None
check(bool(seen) and first[1:4] == ("decision", "compliance.check", "allow"), "the stream's first event is the allow decision", str(first))
check(bool(seen) and first[0] < finished - 2, "that decision arrived while the review was still running", f"{(finished - first[0]) if seen else 0:.1f}s before the reply")
on_ledger = db.ledger.count_documents({"run_id": run_id})
check(len(seen) == on_ledger and not t.is_alive(), f"the stream delivered all {on_ledger} events of the run and closed when it ended", f"{len(seen)} of {on_ledger}")
print("     events:", [f"{e[1]}:{e[2]}" for e in seen])
check(r["status"] == "completed" and next(c["data"] for c in r["cards"] if c["type"] == "compliance_report")["verdict"] == "pass", "a compliant ad passes")
filed = next(c["data"] for c in r["cards"] if c["type"] == "campaign")
q = http.post("/chat", headers=mkt, json={"thread_id": thread, "message": "What is the call to action in it?"}).json()
card = next((c["data"] for c in q["cards"] if c["type"] == "campaign"), {})
check(q["intent"] == "ask" and card.get("id") == filed["id"], "a follow-up 'it' resolves to the ad just reviewed in this conversation", f"{q['intent']} {card.get('name')}")
print("     answer:", q["reply"][:140], "| grounding:", q["grounding"]["band"])
check(db.checkpoints.count_documents({}) > 0, "conversation state is stored in MongoDB (checkpoints)")

print("Stop mid-run")
run_id = str(uuid.uuid4()); result = {}
def review(): result.update(http.post("/chat", headers=mkt, json={"thread_id": "stop-" + run_id, "run_id": run_id, "ad": {**AD, "channel": "email", "name": "Extras stop", "text": RUNNING + " Now."}}).json())
t = threading.Thread(target=review); t.start(); time.sleep(3.0)
stop = http.post(f"/runs/{run_id}/stop", headers=mkt).json()
t.join(timeout=300)
events = [(e["event"], e["action"]) for e in db.ledger.find({"run_id": run_id}).sort("_id", 1)]
check(stop.get("stop_requested") is True, "stop was accepted while the review was running")
check(result.get("status") == "stopped" and events[-1][0] == "stop", "the run halted before its next step", f"{result.get('status')} {events}")
check(db.campaigns.count_documents({"name": "Extras stop"}) == 0, "nothing was filed after the stop")
check(http.get(f"/runs/{run_id}", headers=mkt).json()["status"] == "stopped", "the run is recorded as stopped")
print("     events:", events)

print("Expiry and validators")
check(db.memories.count_documents({"ref": "nat-epi-rewards-hold"}) == 0, "the five-minute memory has been removed by the TTL index")
for name, doc in (("ledger event with no actor", ("ledger", {"event": "decision"})), ("memory of an unknown kind", ("memories", {"kind": "rumour", "text": "x", "scope": {"team": "national"}, "visibility_roles": ["manager"], "status": "active", "source": {"type": "agent"}, "created_by": "x", "created_at": __import__("datetime").datetime.now()}))):
    try:
        db[doc[0]].insert_one(doc[1]); check(False, f"validator rejects a {name}")
    except WriteError:
        check(True, f"validator rejects a {name}")
bad = db.ledger.count_documents({"$or": [{"actor.user_id": {"$exists": False}}, {"auth.method": {"$exists": False}}, {"ts": {"$not": {"$type": "date"}}}]})
check(bad == 0, f"all {db.ledger.count_documents({})} ledger events written by the app carry actor, auth method and a real timestamp")
runs = list(db.runs.find({"tokens": {"$exists": True}}))
check(len(runs) > 0 and all("in" in r["tokens"] for r in runs), f"token counts are recorded on runs ({len(runs)} runs)")
print(f"\n{ok_count[0]} of {sum(ok_count)} checks passed.")
raise SystemExit(1 if ok_count[1] else 0)
