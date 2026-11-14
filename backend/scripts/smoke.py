"""Live end-to-end check against a running backend and a seeded database (the NorthPlay data set).

    python -m scripts.load_db --db greenlight_scratch --password "$SEED_PASSWORD"
    MONGODB_DB=greenlight_scratch uvicorn app.main:app --port 8000     # in one terminal
    python -m scripts.smoke                                            # in another

Run it against a scratch database, not the shared one: it uploads the three demo ads, files and
releases ads, edits and rolls back a policy clause, and saves and forgets a team instruction.

It uses real model and embedding calls. On a Voyage account limited to three requests a minute it
takes several minutes, because the backend waits when it is rate limited.
"""
from __future__ import annotations

import argparse
import sys
import uuid

import httpx

from app.core.config import SOURCE_DATA_DIR, get_settings

DEMO = SOURCE_DATA_DIR / "demo_ads"
CHANNEL = "Instagram (paid social)"
INSTRUCTION = "every NorthPlay ad must include the line 'Set a limit. Stick to it.'"

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    results.append((bool(ok), what))
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"   [{detail}]" if detail and not ok else ""), flush=True)
    return bool(ok)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    args = p.parse_args()
    password = get_settings().seed_password
    if not password:
        print("SEED_PASSWORD is not set in .env; cannot log in as the seeded users.")
        return 2
    http = httpx.Client(base_url=args.base, timeout=600)

    def login(email: str) -> tuple[dict, str]:
        r = http.post("/auth/login", json={"email": email, "password": password})
        check(r.status_code == 200, f"login {email.split('@')[0]}", r.text[:120])
        token = r.json().get("token", "")
        return {"Authorization": f"Bearer {token}"}, token

    def review_image(headers: dict, name: str, title: str, **extra) -> dict:
        up = http.post("/assets", headers=headers, files={"file": (name, (DEMO / name).read_bytes(), "image/png")}).json()
        run_id = str(uuid.uuid4())
        body = {"thread_id": f"smoke-{run_id}", "run_id": run_id, "file_id": up["file_id"], "ad": {"name": title, "channel": CHANNEL}, **extra}
        r = http.post("/chat", headers=headers, json=body).json()
        r["report"] = next((c["data"] for c in r.get("cards", []) if c["type"] == "compliance_report"), {})
        r["ad"] = next((c["data"] for c in r.get("cards", []) if c["type"] == "campaign"), {})
        return r

    def refs(report: dict) -> tuple[set, list]:
        return {v["fundamental_key"] for v in report.get("violations", []) if v.get("fundamental_key")}, [v for v in report.get("violations", []) if v.get("memory_id")]

    print("health:", http.get("/health").json())
    (legal, _), (marketer, marketer_token), (support, support_token), (alberta, _) = (
        login("ethan.cho@northplay.test"), login("amira.haddad@northplay.test"), login("jordan.blake@northplay.test"), login("manager.alberta@northplay.test"),
    )

    print("\nThe three demo ads")
    r = http.post("/compliance/check", headers=support, json={"text": "Bet now", "channel": CHANNEL})
    check(r.status_code == 403, "support cannot review an ad", str(r.status_code))

    one = review_image(marketer, "demo_01_hockey_night_live.png", "Smoke: Hockey Night Live")
    check(one["report"].get("decision") == "approved", "demo 1 (clean ad) is approved", f"{one['report'].get('decision')} {refs(one['report'])[0]}")
    check(one["ad"].get("modality") == "image" and one["ad"].get("status") == "pending_review", "it is filed with its image, pending review")
    log = http.get(f"/audit?run_id={one['run_id']}", headers=marketer).json()
    check([e["event"] for e in log[:2]] == ["decision", "outcome"] and log[0]["decision"] == "allow", "the allow decision is on the ledger before the outcome")

    two = review_image(marketer, "demo_02_big_game_bonus.png", "Smoke: Big Game bonus")
    clauses, mems = refs(two["report"])
    check(two["report"].get("decision") == "rejected" and {"REG-12", "REG-13"} <= clauses, "demo 2 (public bonus offer) is rejected on REG-12 and REG-13", f"{two['report'].get('decision')} {clauses}")
    check(len(mems) >= 1, "and on an internal Slack decision as well", str([m["memory_id"] for m in mems]))

    three = review_image(marketer, "demo_03_play_smart_breaks.png", "Smoke: Play Smart breaks")
    clauses, mems = refs(three["report"])
    check(three["report"].get("decision") == "rejected" and len(mems) >= 1, "demo 3 is rejected because of an internal decision", f"{three['report'].get('decision')}")
    check(not clauses, "no regulation is cited against demo 3: the rejection rests on Slack context alone", str(clauses))
    check(any("Moreau" in (v.get("evidence", {}).get("memory_text") or "") for v in mems), "the decision it cites is the one about Jake Moreau")
    replay = http.post("/compliance/check", headers=marketer, json={"campaign_id": three["ad"]["id"], "use_memory": False}).json()
    check(replay.get("decision") != "rejected" and replay.get("memories_used") == [], "replayed without memory, the same ad is not rejected", str(replay.get("decision")))

    print("\nRegenerate, approve, release")
    check(http.post(f"/campaigns/{three['ad']['id']}/approve", headers=legal, json={}).status_code == 409, "a rejected ad cannot be approved")
    regen = http.post(f"/campaigns/{three['ad']['id']}/regenerate", headers=marketer, json={}).json()
    ok = regen.get("status") == "regenerated" and regen["report"]["verdict"] == "pass" and (regen["campaign"].get("asset") or {}).get("type") == "image"
    if check(ok, "demo 3 is regenerated as a new banner that passes the same review", str(regen.get("status"))):
        check("Moreau" not in regen["campaign"]["text"], "the regenerated copy no longer names him")
        img = http.get(regen["campaign"]["asset"]["url"] + f"?token={marketer_token}")
        check(img.status_code == 200 and img.content[:4] == b"\x89PNG", "the new banner is served")
        check(http.get(regen["campaign"]["asset"]["url"] + f"?token={support_token}").status_code == 404, "support cannot fetch an unreleased ad's file")
    check(http.post(f"/campaigns/{one['ad']['id']}/approve", headers=marketer, json={}).status_code == 403, "a marketer cannot approve")
    check(http.post(f"/campaigns/{one['ad']['id']}/approve", headers=legal, json={}).status_code == 200, "legal approves demo 1")

    print("\nPolicy edit, stale release, rollback")
    clause = next(c for c in http.get("/fundamentals", headers=legal).json() if c["key"] == "REG-09")
    edit = {"text": clause["text"] + " (smoke test edit)", "reason": "smoke test"}
    check(http.put(f"/fundamentals/{clause['id']}", headers=legal, json=edit).status_code == 401, "a policy edit without the password is refused")
    edited = http.put(f"/fundamentals/{clause['id']}", headers=legal, json={**edit, "password": password})
    check(edited.status_code == 200 and edited.json()["version"] == clause["version"] + 1, "with the password it becomes the next version")
    stale = http.post(f"/campaigns/{one['ad']['id']}/release", headers=marketer, json={})
    check(stale.status_code == 409 and "REG-09" in " ".join(stale.json().get("changes", [])), "release is refused: the approval is stale", stale.text[:160])
    rolled = http.post(f"/runs/{edited.json()['run_id']}/rollback", headers=legal)
    check(rolled.status_code == 200 and rolled.json()["status"] == "rolled_back", "rollback restores the earlier version", rolled.text[:160])
    check(http.post(f"/campaigns/{one['ad']['id']}/approve", headers=legal, json={}).status_code == 200, "legal approves again")
    check(http.post(f"/campaigns/{one['ad']['id']}/release", headers=marketer, json={}).json().get("status") == "released", "release succeeds")

    print("\nA new instruction changes the next verdict")
    draft = http.post("/chat", headers=legal, json={"thread_id": f"smoke-legal-{uuid.uuid4()}", "message": "From now on, " + INSTRUCTION}).json()
    proposal = next((c["data"] for c in draft.get("cards", []) if c["type"] == "memory_change"), None)
    if check(proposal is not None and proposal["status"] == "proposed" and proposal["requires_password"], "the agent drafts the instruction and saves nothing", draft.get("reply", "")[:120]):
        body = {"kind": proposal["kind"], "text": proposal["after"], "scope": proposal["scope"], "reason": "smoke test"}
        check(http.post("/memories", headers=legal, json=body).status_code == 401, "saving it without the password is refused")
        check(http.post("/memories", headers=marketer, json={**body, "password": password}).status_code == 403, "a marketer cannot save a team instruction")
        saved = http.post("/memories", headers=legal, json={**body, "password": password}).json()
        flagged = http.post("/compliance/check", headers=marketer, json={"campaign_id": one["ad"]["id"]}).json()
        check(any(v.get("memory_id") == saved["id"] for v in flagged["violations"]), "the ad that was approved is now flagged, citing the new instruction", str(flagged.get("decision")))
        check(all(m["id"] != saved["id"] for m in http.get("/memories", headers=alberta).json()), "the Alberta team cannot see it")
        gone = http.request("DELETE", f"/memories/{saved['id']}", headers=legal, json={"reason": "smoke test cleanup", "password": password})
        check(gone.status_code == 204, "forgetting it needs the password and succeeds")

    print("\nQuestions and scope")
    r = http.post("/chat", headers=support, json={"thread_id": f"smoke-support-{uuid.uuid4()}", "message": "A player saw an ad about setting limits. What did it say?"}).json()
    card = next((c["data"] for c in r.get("cards", []) if c["type"] == "campaign"), {})
    check(r.get("intent") == "ask" and card.get("status") == "released" and card.get("asset", {}).get("type") == "image", "support gets a released ad, with its image", f"{r.get('intent')} {card.get('name')} {card.get('status')}")
    check(bool(r.get("grounding")), "the answer says where it came from", r.get("reply", "")[:140])
    r = http.post("/chat", headers=support, json={"thread_id": f"smoke-support-{uuid.uuid4()}", "message": "From now on all ads must mention our app."}).json()
    check(r.get("status") == "denied", "support cannot change team memory, and the refusal is recorded")
    check(len(http.get("/memories", headers=alberta).json()) == 0, "the Alberta team sees none of Ontario's memories")
    check(all(c["status"] == "released" for c in http.get("/campaigns", headers=support).json()), "support sees released ads only")
    leadership = [m for m in http.get("/memories", headers=marketer).json() if (m.get("source") or {}).get("channel") == "leadership"]
    check(not leadership and any((m.get("source") or {}).get("channel") == "leadership" for m in http.get("/memories", headers=legal).json()), "leadership-channel decisions are visible to managers only")

    failed = [what for ok, what in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    for what in failed:
        print(f"  FAILED: {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
