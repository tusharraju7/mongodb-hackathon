"""Model access. Two tiers: the main model gives the compliance verdict, the fast model does the rest.

Notes for Claude 5.5 models, which shape this file:
- Sampling parameters (temperature, top_p) are rejected, so none are sent.
- Forced tool choice is rejected on Opus 5.5, so structured output uses the native JSON-schema
  method, never LangChain's default function-calling method.
- Thinking is always on for Opus 5.5; depth is set with `effort`.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core import gate
from app.core.config import get_settings

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 16000  # non-streaming ceiling that stays inside SDK timeouts


class ModelRefused(Exception):
    """The model declined the request. Callers fail closed: no verdict, no file."""


class ModelFailed(Exception):
    """The model returned something that could not be parsed into the expected shape."""


@dataclass
class TokenUsage:
    """Running token count for one run. Passed into every call so `runs.tokens` can be recorded."""

    input: int = 0
    output: int = 0
    cached: int = 0  # input tokens served from the prompt cache, billed at a fraction of the price
    calls: list[dict] = field(default_factory=list)

    def add(self, label: str, usage: Optional[dict], **extra) -> None:
        usage = usage or {}
        i, o = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        details = usage.get("input_token_details") or {}
        cached = int(details.get("cache_read", 0) or 0)
        self.input += i
        self.output += o
        self.cached += cached
        self.calls.append({"step": label, "in": i, "out": o, "cached": cached, "cache_written": int(details.get("cache_creation", 0) or 0), **extra})

    def as_dict(self) -> dict:
        return {"in": self.input, "out": self.output, **({"cached": self.cached} if self.cached else {})}


@lru_cache
def main_model():
    """Compliance verdict and, when needed, one repair of corrected copy."""
    s = get_settings()
    return init_chat_model(s.llm_model, max_tokens=MAX_TOKENS, output_config={"effort": s.llm_effort})


@lru_cache
def fast_model():
    """Router, claim extraction, image reading, Q&A, drafting. Accepts image input."""
    s = get_settings()
    return init_chat_model(s.llm_fast_model, max_tokens=MAX_TOKENS, output_config={"effort": s.llm_fast_effort})


def _name(model) -> Optional[str]:
    return getattr(model, "model", None) or getattr(model, "model_name", None)


def _effort(model) -> Optional[str]:
    return (getattr(model, "output_config", None) or getattr(model, "model_kwargs", {}).get("output_config") or {}).get("effort")


def prompts_version() -> str:
    from app.agent.prompts import PROMPT_VERSION

    return PROMPT_VERSION


def cached_system(stable: list[str]) -> list[dict]:
    """A system prompt made of parts that do not change from call to call, marked for prompt caching.

    Caching matches on an exact prefix, so only text that is identical every time belongs here.
    Anything about the particular request goes in the user message.
    """
    blocks = [{"type": "text", "text": part} for part in stable if part]
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def image_block(data: bytes, mime: str) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": base64.standard_b64encode(data).decode()},
    }


def call_structured(
    model,
    schema: Type[T],
    *,
    system: Any,
    user: Any,
    label: str,
    usage: Optional[TokenUsage] = None,
    run_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> T:
    """One model call that returns `schema`. `system` and `user` are each a string or a list of content blocks.

    The run id and intent are attached as trace metadata so a ledger entry can be matched to its
    LangSmith trace. Never pass a password or a raw audio file through here.
    """
    runnable = model.with_structured_output(schema, method="json_schema", include_raw=True)
    config = {
        "run_name": label,
        "tags": [t for t in ("greenlight", intent) if t],
        "metadata": {k: v for k, v in {"run_id": run_id, "intent": intent, "step": label}.items() if v},
    }
    started = time.time()
    try:
        result = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)], config=config)
    except Exception as exc:
        gate.emit("model_call", f"model.{label}", params={"model": _name(model), "prompt_version": prompts_version()},
                  result={"status": "error", "summary": type(exc).__name__}, duration_ms=int((time.time() - started) * 1000))
        gate.count(model_calls=1)
        raise
    raw = result.get("raw")
    if usage is not None and raw is not None:
        usage.add(label, getattr(raw, "usage_metadata", None))
    stop_reason = (getattr(raw, "response_metadata", None) or {}).get("stop_reason")
    meta = getattr(raw, "usage_metadata", None) or {}
    spent = {"in": int(meta.get("input_tokens", 0)), "out": int(meta.get("output_tokens", 0)), "cached": int((meta.get("input_token_details") or {}).get("cache_read", 0) or 0)}
    # The ledger holds fingerprints of the prompt and the answer, not copies; the full text is in the trace.
    gate.emit(
        "model_call", f"model.{label}", duration_ms=int((time.time() - started) * 1000), tokens=spent,
        params={"model": _name(model), "effort": _effort(model), "prompt_version": prompts_version(), "prompt_hash": gate.digest([system, user]),
                "output_hash": gate.digest(getattr(raw, "content", None)), "schema": schema.__name__, "trace_id": getattr(raw, "id", None)},
        result={"status": "refused" if stop_reason == "refusal" else "ok" if result.get("parsed") is not None else "error", "summary": f"{label}: {stop_reason or 'done'}"},
    )
    gate.count(model_calls=1, tokens=spent["in"] + spent["out"])
    if stop_reason == "refusal":
        raise ModelRefused(f"{label}: the model declined this request")
    parsed = result.get("parsed")
    if parsed is None:
        raise ModelFailed(f"{label}: no parsable output (stop_reason={stop_reason}, error={result.get('parsing_error')})")
    return parsed
