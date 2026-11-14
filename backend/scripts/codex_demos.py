"""Run three images through the real pipeline, preserving the Claude baseline and Atlas."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from app.core import llm
from app.core.config import REPO_ROOT, SOURCE_DATA_DIR, get_settings
from app.core.profile import get_profile
from app.agent.prompts import PROMPT_VERSION
from app.services import compliance, media
from app.services.fixture_sources import SeedSources, load_seed, seed_identity
from scripts.dry_run import DEMO_CHANNEL, DEMO_EXPECTED


def main():
    settings = get_settings()
    if not settings.llm_model.startswith("codex:") or not settings.llm_fast_model.startswith("codex:"):
        raise RuntimeError("Configure both LLM_MODEL and LLM_FAST_MODEL with codex: first")
    identity = seed_identity(next(u["email"] for u in load_seed("users") if u["role"] == "marketer"))
    profile, sources = get_profile(), SeedSources()
    destination = REPO_ROOT / "docs" / "results" / "codex-demos.json"
    destination.parent.mkdir(exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "prompt_version": PROMPT_VERSION,
               "assessment_model": settings.llm_model, "fast_model": settings.llm_fast_model,
               "effort": settings.llm_effort, "fast_effort": settings.llm_fast_effort,
               "channel": DEMO_CHANNEL, "identity": identity.email, "memory_enabled": True,
               "sources": "backend/seed (no Atlas writes)", "results": []}
    for filename, expected, story in DEMO_EXPECTED:
        print(f"Reviewing {filename}...", flush=True)
        usage, started = llm.TokenUsage(), time.monotonic()
        image = (SOURCE_DATA_DIR / "demo_ads" / filename).read_bytes()
        reading = media.read_image_bytes(image, "image/png", usage=usage)
        context = {"product": profile["product"], "region": profile["region"], "channel": DEMO_CHANNEL,
                   "modality": "image", "visual_notes": reading["visual_notes"], "fine_print_legible": reading["fine_print_legible"]}
        report = compliance.review(reading["text"], context, identity, str(uuid.uuid4()),
                                   use_memory=True, sources=sources, usage=usage).report
        seconds = round(time.monotonic() - started, 2)
        payload["results"].append({"file": filename, "sha256": hashlib.sha256(image).hexdigest(),
                                   "claude_decision": expected, "reading": reading, "report": report.model_dump(mode="json"),
                                   "seconds": seconds, "tokens": usage.as_dict(), "calls": usage.calls})
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{filename}: {report.decision}; confidence {report.confidence.score}; {seconds}s; {usage.as_dict()}", flush=True)
    (REPO_ROOT / "frontend" / "src" / "codex-results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Local Codex versus Claude: three demo ads", "", f"Generated {payload['generated_at']}. Prompt {PROMPT_VERSION}.", "",
             f"Assessment: `{settings.llm_model}`; smaller steps: `{settings.llm_fast_model}`; both low reasoning.", "",
             "Same image inputs, channel, policy pipeline and scoped seed memory. Claude baseline: [RESULTS.md](RESULTS.md).",
             "These are fixture-source pipeline runs, not authenticated browser uploads. No Atlas records or memories were changed.", "",
             "| Ad | Claude decision | Codex decision | Confidence | Time |", "|---|---|---|---|---|"]
    for item in payload["results"]:
        r = item["report"]
        lines.append(f"| {item['file']} | {item['claude_decision']} | {r['decision']} | {r['confidence']['score']} | {item['seconds']}s |")
    lines += ["", "Confidence is computed by the existing backend; it is not a risk score or a probability. Timing includes CLI startup, image reading, extraction, retrieval and assessment. Single runs are not a speed benchmark.", "",
              "Full image readings, findings, source references, timings and CLI token counts: [JSON results](results/codex-demos.json).", ""]
    for item in payload["results"]:
        lines += [f"## {item['file']}", "", item["report"]["summary"], ""]
        for finding in item["report"]["violations"]:
            lines.append(f"- {finding.get('fundamental_key') or finding.get('memory_id')}: {finding['explanation']}")
    (REPO_ROOT / "docs" / "RESULTS_CODEX.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
