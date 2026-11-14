"""Greenlight backend. Run from backend/:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import importlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings

app = FastAPI(title="Greenlight", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers are added as they are built. A router that does not exist yet is skipped, so the app
# always starts.
for name in ("auth", "chat", "compliance", "campaigns", "assets", "fundamentals", "memories", "audit", "runs"):
    try:
        app.include_router(importlib.import_module(f"app.routers.{name}").router)
    except ModuleNotFoundError as exc:
        if exc.name != f"app.routers.{name}":
            raise


@app.get("/health")
def health() -> dict:
    s = get_settings()
    status = {"status": "ok", "database": s.mongodb_db, "model": s.llm_model, "fast_model": s.llm_fast_model}
    try:
        from app.core.db import get_client

        get_client().admin.command("ping")
        status["mongodb"] = "reachable"
    except Exception as exc:  # the app still answers, so the web app can show what is wrong
        status["mongodb"] = f"unreachable: {type(exc).__name__}"
    return status


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Map domain errors to the statuses in docs/CONTRACTS.md. Anything else is a 500 with no detail leaked."""
    name = type(exc).__name__
    if name == "Denied":
        return _error(403, "denied", str(exc))
    if name == "RunStopped":
        return _error(409, "stopped", str(exc))
    if name == "StaleApproval":
        return _error(409, "stale_approval", str(exc), changes=getattr(exc, "changes", []))
    if name == "NotFound":
        return _error(404, "not_found", str(exc))
    if name == "StepUpFailed":
        return _error(401, "step_up_failed", str(exc))
    if name == "EmbeddingRateLimited":
        return _error(429, "embedding_rate_limited", str(exc))
    if name in ("ModelRefused", "ModelFailed"):
        return _error(502, "model_error", str(exc))
    return _error(500, "internal_error", "Something went wrong. Nothing was changed.")
