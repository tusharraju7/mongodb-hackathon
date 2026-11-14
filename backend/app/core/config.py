"""Settings, read once from the repo-root .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
SEED_DIR = BACKEND_ROOT / "seed"

load_dotenv(REPO_ROOT / ".env")

# LangSmith reads its settings from the process environment. Where traces go is set there, by either
# LANGSMITH_PROJECT or the LANGSMITH_AGENT_ID / LANGSMITH_AGENT_ENVIRONMENT pair. Set one, never both:
# LangSmith refuses to trace when both are present.


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_db: str
    llm_model: str
    llm_fast_model: str
    llm_effort: str
    llm_fast_effort: str
    voyage_api_key: str
    voyage_model: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    jwt_secret: str
    seed_password: str
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        mongodb_uri=env("MONGODB_URI", ""),
        mongodb_db=env("MONGODB_DB", "greenlight"),
        llm_model=env("LLM_MODEL", "anthropic:claude-opus-5-5"),
        llm_fast_model=env("LLM_FAST_MODEL", "anthropic:claude-haiku-5-5"),
        # Measured on the running example: "low" returns the same findings as "medium" in about 10
        # seconds instead of 35. Raise it for more deliberation at the cost of latency.
        llm_effort=env("LLM_EFFORT", "low"),
        llm_fast_effort=env("LLM_FAST_EFFORT", "low"),
        voyage_api_key=env("VOYAGE_API_KEY", ""),
        voyage_model=env("VOYAGE_MODEL", "voyage-3.5"),
        elevenlabs_api_key=env("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=env("ELEVENLABS_VOICE_ID", ""),
        jwt_secret=env("JWT_SECRET", ""),
        seed_password=env("SEED_PASSWORD", ""),
        cors_origins=tuple(
            o.strip() for o in env("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        ),
    )
