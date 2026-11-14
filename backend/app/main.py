"""Greenlight backend. Run from backend/:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import importlib
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import gate, llm, security
from app.core.config import get_settings
from app.core.embeddings import EmbeddingRateLimited
from app.services import campaigns, fundamentals, media, memory

app = FastAPI(title="Greenlight", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Run-Id"],
)

class RequestStartsAsHuman:
    """An action is the agent's only inside a lane. Each request begins as its caller's own act."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        with gate.fresh_request():
            await self.inner(scope, receive, send)


app.add_middleware(RequestStartsAsHuman)

for name in ("auth", "chat", "compliance", "campaigns", "assets", "fundamentals", "memories", "audit", "runs", "governance"):
    app.include_router(importlib.import_module(f"app.routers.{name}").router)


@app.on_event("startup")
def notice_crashed_runs() -> None:
    """A run left `running` by a process that died is marked interrupted, so it can be resumed or rolled back."""
    try:
        gate.sweep_interrupted()
    except Exception:
        pass  # the database may be unreachable; /health reports that


@app.exception_handler(gate.SimulatedCrash)
async def simulated_crash(request: Request, exc: gate.SimulatedCrash) -> JSONResponse:
    # Fault injection only. The run is left untouched, exactly as a dead process would leave it.
    return JSONResponse(status_code=500, content={"error": "crashed", "message": str(exc)})


@app.get("/health")
def health() -> dict:
    s = get_settings()
    status = {"status": "ok", "database": s.mongodb_db, "model": s.llm_model, "fast_model": s.llm_fast_model}
    # Shown so a test or a demo can tell whether a crash can be staged, and how soon it is noticed.
    status["fault_injection"] = os.environ.get("ALLOW_FAULT_INJECTION", "").lower() == "true"
    status["run_stale_seconds"] = gate.RUN_STALE_SECONDS
    try:
        from app.core.db import get_client

        get_client().admin.command("ping")
        status["mongodb"] = "reachable"
    except Exception as exc:  # the app still answers, so the web app can show what is wrong
        status["mongodb"] = f"unreachable: {type(exc).__name__}"
    return status


# Domain errors and the statuses they map to (docs/CONTRACTS.md section 7).
ERRORS: dict[type, tuple[int, str]] = {
    gate.Denied: (403, "denied"),
    gate.RunStopped: (409, "stopped"),
    security.StepUpFailed: (401, "step_up_failed"),
    campaigns.StaleApproval: (409, "stale_approval"),
    campaigns.NotApprovable: (409, "not_approvable"),
    campaigns.NotFound: (404, "not_found"),
    fundamentals.NotFound: (404, "not_found"),
    memory.NotFound: (404, "not_found"),
    media.UnsupportedMedia: (415, "unsupported_media"),
    EmbeddingRateLimited: (429, "embedding_rate_limited"),
    llm.ModelRefused: (502, "model_refused"),
    llm.ModelFailed: (502, "model_failed"),
}


def _handler(status: int, code: str):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        body = {"error": code, "message": str(exc)}
        if isinstance(exc, campaigns.StaleApproval):
            body["changes"] = exc.changes
        return JSONResponse(status_code=status, content=body)

    return handle


for _exc, (_status, _code) in ERRORS.items():
    app.add_exception_handler(_exc, _handler(_status, _code))
