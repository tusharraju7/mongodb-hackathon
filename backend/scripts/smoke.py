"""Live end-to-end check against a running backend and the seeded shared database.

    uvicorn app.main:app --port 8000          # in one terminal
    python -m scripts.smoke                   # in another

Needs: the database created and seeded per docs/MONGODB_SETUP.md, and SEED_PASSWORD in .env set to
the password the seeded users were given. It uses real model, embedding and (with --audio) speech
calls, and it writes test ads, one team instruction and ledger events to the database, cleaning up
the instruction at the end.

On a Voyage account limited to three requests a minute this takes several minutes, because each
review makes two embedding requests and the backend waits when it is rate limited.
"""
from __future__ import annotations

import argparse
import sys
import uuid

import httpx

from app.core.config import get_settings

RUNNING = "Guaranteed approval! Enjoy 0% interest for 12 months and earn $300 cash back. Apply today."
AD = {"product": "credit_card", "offer_id": "TCB-FALL-2026", "region": "CA", "channel": "email", "budget": {"amount": 20000, "currency": "CAD"}}
INSTRUCTION = "Quebec card ads must include the line 'Sous réserve de l'approbation du crédit.'"
EXPECTED = {"credit.approval_claims", "policy.offer_accuracy", "credit.intro_rate_disclosure", "credit.bonus_conditions", "regional.ca.email_consent", "brand.required_footer"}

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    results.append((bool(ok), what))
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"   [{detail}]" if detail and not ok else ""))
    return bool(ok)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--audio", action="store_true", help="also upload, review and regenerate an audio ad (uses ElevenLabs)")
    args = p.parse_args()
    password = get_settings().seed_password
    if not password:
        print("SEED_PASSWORD is not set in .env; cannot log in as the seeded users.")
        return 2
    http = httpx.Client(base_url=args.base, timeout=300)

    def login(name: str) -> dict:
        r = http.post("/auth/login", json={"email": f"{name}@tamarack.test", "password": password})
        check(r.status_code == 200, f"login {name}", r.text[:120])
        return {"Authorization": f"Bearer {r.json().get('token', '')}"}

    print("health:", http.get("/health").json())
    mgr, mkt, sales = login("manager.national"), login("marketer.national"), login("sales.national")
    qc_mgr, qc_mkt = login("manager.quebec"), login("marketer.quebec")

    print("\nUC1 review")
    r = http.post("/compliance/check", headers=sales, json={**AD, "text": RUNNING})
    check(r.status_code == 403, "sales cannot review", str(r.status_code))
    run_id = str(uuid.uuid4())
    r = http.post("/chat", headers=mkt, json={"thread_id": f"smoke-{run_id}", "run_id": run_id, "ad": {**AD, "text": RUNNING, "name": "Smoke test ad"}}).json()
    report = next(c["data"] for c in r["cards"] if c["type"] == "compliance_report")
    ad = next(c["data"] for c in r["cards"] if c["type"] == "campaign")
    cited = {v["fundamental_key"] for v in report["violations"] if v.get("fundamental_key")}
    check(report["verdict"] == "blocked" and report["route"] == "human_review", "running example is blocked and goes to human review", f"{report['verdict']}/{report['route']}")
    check(EXPECTED <= cited, "the six expected clauses are cited", f"missing {sorted(EXPECTED - cited)}")
    check(report["confidence"]["band"] == "high" and all("confidence" in v and v["reasoning"] for v in report["violations"]), "confidence and reasoning on every finding")
    log = http.get(f"/audit?run_id={run_id}", headers=mkt).json()
    check([e["event"] for e in log[:2]] == ["decision", "outcome"] and log[0]["decision"] == "allow", "decision is on the ledger before the outcome")
    r = http.post("/compliance/check", headers=mkt, json={**AD, "offer_id": "NO-SUCH-OFFER", "text": RUNNING}).json()
    check(r.get("missing_inputs") == ["offer_id"], "unknown offer stops the review")
    r = http.post("/compliance/check", headers=qc_mkt, json={**AD, "region": "CA-QC", "text": "Get $300 cash back after $1,500 in purchases in your first 3 months. Conditions apply. Unsubscribe"}).json()
    check("regional.qc.french_language" in {v.get("fundamental_key") for v in r["violations"]}, "English-only Quebec ad cites the French-language clause")

    print("\nUC1 regenerate, approve, release")
    check(http.post(f"/campaigns/{ad['id']}/approve", headers=mgr, json={}).status_code == 409, "a blocked ad cannot be approved")
    regen = http.post(f"/campaigns/{ad['id']}/regenerate", headers=mkt, json={}).json()
    check(regen.get("status") == "regenerated" and regen["report"]["verdict"] == "pass", "regenerated version passes the same review", str(regen.get("status")))
    check(regen.get("campaign", {}).get("version") == 2 and regen["campaign"]["source"] == "regenerated", "filed as version 2, marked regenerated")
    check(all(c["id"] != ad["id"] for c in http.get("/campaigns", headers=sales).json()), "sales cannot see it before release")
    check(http.post(f"/campaigns/{ad['id']}/approve", headers=mkt, json={}).status_code == 403, "a marketer cannot approve")
    check(http.post(f"/campaigns/{ad['id']}/approve", headers=mgr, json={}).status_code == 200, "manager approves")

    print("\nUC4 policy edit, stale release, rollback")
    clause = next(c for c in http.get("/fundamentals", headers=mgr).json() if c["key"] == "credit.intro_rate_disclosure")
    edit = {"text": clause["text"] + " (smoke test edit)", "reason": "smoke test"}
    check(http.put(f"/fundamentals/{clause['id']}", headers=mgr, json=edit).status_code == 401, "policy edit without the password is refused")
    edited = http.put(f"/fundamentals/{clause['id']}", headers=mgr, json={**edit, "password": password})
    check(edited.status_code == 200 and edited.json()["version"] == clause["version"] + 1, "policy edit with the password bumps the version")
    stale = http.post(f"/campaigns/{ad['id']}/release", headers=mkt, json={})
    check(stale.status_code == 409 and "credit.intro_rate_disclosure" in " ".join(stale.json().get("changes", [])), "release is refused: approval is stale", stale.text[:160])
    rolled = http.post(f"/runs/{edited.json()['run_id']}/rollback", headers=mgr)
    check(rolled.status_code == 200 and rolled.json()["status"] == "rolled_back", "rollback restores the policy version", rolled.text[:160])
    check(http.post(f"/campaigns/{ad['id']}/approve", headers=mgr, json={}).status_code == 200, "manager approves again")
    check(http.post(f"/campaigns/{ad['id']}/release", headers=mkt, json={}).json().get("status") == "released", "release succeeds")

    print("\nUC5 questions")
    r = http.post("/chat", headers=sales, json={"thread_id": f"smoke-sales-{run_id}", "message": "A customer got an email about $300 cash back on the card. What are the conditions?"}).json()
    check(r["intent"] == "ask" and any(c["type"] == "campaign" for c in r["cards"]) and r.get("grounding"), "sales gets the released ad and a grounded answer", r["reply"][:120])
    r = http.post("/chat", headers=sales, json={"thread_id": f"smoke-sales-{run_id}", "message": "From now on all ads must mention our mobile app."}).json()
    check(r["status"] == "denied", "sales cannot change team memory, and it is recorded", r["status"])

    print("\nUC4 memory changes the next verdict")
    qc_ad = next((c for c in http.get("/campaigns", headers=qc_mkt).json() if c["name"] == "Courriel remises d'automne"), None)
    if check(qc_ad is not None, "seeded Quebec email is in the library"):
        draft = http.post("/chat", headers=qc_mgr, json={"thread_id": f"smoke-qc-{run_id}", "message": "From now on, " + INSTRUCTION}).json()
        proposal = next((c["data"] for c in draft["cards"] if c["type"] == "memory_change"), None)
        if check(proposal is not None and proposal["status"] == "proposed", "the agent drafts the instruction and saves nothing", draft["reply"][:120]):
            body = {"kind": proposal["kind"], "text": proposal["after"], "scope": proposal["scope"], "reason": "smoke test"}
            check(http.post("/memories", headers=qc_mgr, json=body).status_code == 401, "saving it without the password is refused")
            saved = http.post("/memories", headers=qc_mgr, json={**body, "password": password}).json()
            flagged = http.post("/compliance/check", headers=qc_mkt, json={"campaign_id": qc_ad["id"]}).json()
            check(any(v.get("memory_id") == saved["id"] for v in flagged["violations"]), "the same ad is now flagged, citing the instruction", flagged["verdict"])
            replay = http.post("/compliance/check", headers=qc_mkt, json={"campaign_id": qc_ad["id"], "use_memory": False}).json()
            check(not any(v.get("memory_id") for v in replay["violations"]) and replay["memories_used"] == [], "replay without memory does not flag it")
            check(all(m["id"] != saved["id"] for m in http.get("/memories", headers=mgr).json()), "the national team cannot see the Quebec instruction")
            gone = http.request("DELETE", f"/memories/{saved['id']}", headers=qc_mgr, json={"reason": "smoke test cleanup", "password": password})
            check(gone.status_code == 204, "forgetting it needs the password and succeeds")

    if args.audio:
        print("\nAudio in and out")
        from app.services import media

        up = http.post("/assets", headers=mkt, files={"file": ("ad.mp3", media.synthesize_bytes(RUNNING), "audio/mpeg")}).json()
        r = http.post("/compliance/check", headers=mkt, json={**AD, "channel": "radio", "file_id": up["file_id"], "name": "Smoke test radio spot", "save": True}).json()
        check(r["verdict"] == "blocked" and r["campaign"]["modality"] == "audio", "uploaded audio is transcribed and reviewed", r.get("verdict"))
        regen = http.post(f"/campaigns/{r['campaign']['id']}/regenerate", headers=mkt, json={}).json()
        ok = regen.get("status") == "regenerated" and regen["campaign"]["asset"] and regen["campaign"]["asset"]["type"] == "audio"
        if check(ok, "regenerated as a new recording"):
            audio = http.get(regen["campaign"]["asset"]["url"], headers=mkt)
            check(audio.status_code == 200 and audio.headers["content-type"].startswith("audio/"), "the new recording streams back")

    failed = [what for ok, what in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    for what in failed:
        print(f"  FAILED: {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
