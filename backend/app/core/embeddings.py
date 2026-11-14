"""Voyage embeddings. One model and one size for the whole project: voyage-3.5, 1024 dimensions.

Documents and queries are embedded with different input types; mixing them up degrades retrieval.
The data teammate's seed script can import these two functions directly.

Calls are kept to a minimum because a Voyage account without a payment method is limited to three
requests a minute: every function here makes one request however many texts it is given, and
repeated texts are served from an in-process cache.
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

import voyageai

from app.core.config import get_settings

DIMENSIONS = 1024
_BATCH = 96
# An unpaid Voyage account also allows only 10,000 tokens a minute, so one request stays well under that.
_BATCH_TOKENS = int(os.environ.get("EMBED_BATCH_TOKENS", "6000"))
_RETRIES = int(os.environ.get("EMBED_RETRIES", "4"))
# A refused request still counts against the limit, so each wait is longer than the last.
_RETRY_WAIT = float(os.environ.get("EMBED_RETRY_WAIT", "22"))
_cache: dict[tuple[str, str, str], list[float]] = {}


class EmbeddingRateLimited(Exception):
    """Voyage refused the request for rate reasons after the retries were used up."""


@lru_cache
def _client() -> voyageai.Client:
    return voyageai.Client(api_key=get_settings().voyage_api_key, max_retries=0, timeout=30)


def _request(texts: list[str], model: str, input_type: str) -> list[list[float]]:
    for attempt in range(_RETRIES + 1):
        try:
            return _client().embed(texts, model=model, input_type=input_type).embeddings
        except voyageai.error.RateLimitError as exc:
            if attempt == _RETRIES:
                raise EmbeddingRateLimited(
                    "The embedding service is rate limited. Without a payment method a Voyage account allows "
                    "three requests and 10,000 tokens a minute; add one in the Voyage dashboard to lift the limit."
                ) from exc
            time.sleep(_RETRY_WAIT * (attempt + 1))
    return []


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    if not texts:
        return []
    model = get_settings().voyage_model
    missing = list(dict.fromkeys(t for t in texts if (model, input_type, t) not in _cache))
    batch: list[str] = []
    size = 0

    def flush() -> None:
        for text, vector in zip(batch, _request(batch, model, input_type)):
            _cache[(model, input_type, text)] = vector

    for text in missing:
        tokens = len(text) // 3 + 1  # a deliberate over-estimate
        if batch and (len(batch) >= _BATCH or size + tokens > _BATCH_TOKENS):
            flush()
            batch, size = [], 0
        batch.append(text)
        size += tokens
    if batch:
        flush()
    return [_cache[(model, input_type, t)] for t in texts]


def embed_documents(texts: list[str]) -> list[list[float]]:
    """For text that will be stored and searched: clauses, ad descriptions, memories."""
    return _embed(texts, "document")


def embed_queries(texts: list[str]) -> list[list[float]]:
    """For search text: an ad, its claims, a question. One request for any number of queries."""
    return _embed(texts, "query")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
