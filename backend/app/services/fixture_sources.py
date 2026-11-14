"""Review sources backed by backend/seed/*.json, with retrieval done in memory.

Used by the dry run and the tests so the review can be exercised before the database exists. It
applies the same scoping rules the MongoDB sources apply in their queries.

Clause and memory embeddings are fetched in a single request and kept on disk under
backend/.cache, so a second dry run makes no document-embedding request at all.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from app.core import embeddings
from app.core.config import BACKEND_ROOT, SEED_DIR, get_settings
from app.models import Identity
from app.services.fundamentals import clause_document

CACHE_FILE = BACKEND_ROOT / ".cache" / "seed_embeddings.json"


def load_seed(name: str) -> list[dict]:
    return json.loads((SEED_DIR / f"{name}.json").read_text())


def _date(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def clause_applies(clause: dict, regions: list[str], product: str, at: datetime) -> bool:
    start, end = _date(clause.get("effective_from")), _date(clause.get("effective_to"))
    return (
        clause.get("status") == "approved"
        and clause.get("region") in regions
        and clause.get("product") in (product, "all")
        and (start is None or start <= at)
        and (end is None or end >= at)
    )


def _digest(text: str) -> str:
    return hashlib.sha256(f"{get_settings().voyage_model}|{text}".encode()).hexdigest()


def embed_with_disk_cache(texts: list[str]) -> list[list[float]]:
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if _digest(t) not in cache]
    if missing:
        for text, vector in zip(missing, embeddings.embed_documents(missing)):
            cache[_digest(text)] = vector
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache))
    return [cache[_digest(t)] for t in texts]


class SeedSources:
    def __init__(self, *, extra_memories: Optional[list[dict]] = None, clause_overrides: Optional[dict[str, dict]] = None, exclude_memory_refs: Optional[set] = None):
        self._offers = {o["_id"]: o for o in load_seed("offers")}
        self._clauses = [{**c, **(clause_overrides or {}).get(c["key"], {})} for c in load_seed("fundamentals")]
        self._memories = [m for m in load_seed("memories") + (extra_memories or []) if m["ref"] not in (exclude_memory_refs or set())]
        self._vectors: Optional[dict[str, list[float]]] = None

    def _load_vectors(self) -> dict[str, list[float]]:
        """One request (or none, when cached) for every clause and memory."""
        if self._vectors is None:
            docs = [clause_document(c) for c in self._clauses] + [m["text"] for m in self._memories]
            self._vectors = dict(zip(docs, embed_with_disk_cache(docs)))
        return self._vectors

    def offer(self, offer_id: str) -> Optional[dict]:
        return self._offers.get(offer_id)

    def applicable_clauses(self, regions: list[str], product: str) -> list[dict]:
        at = datetime.now(timezone.utc)
        return [c for c in self._clauses if clause_applies(c, regions, product, at)]

    def similar_clauses(self, vectors: list[list[float]], regions: list[str], product: str, k: int) -> list[list[tuple[dict, float]]]:
        stored = self._load_vectors()
        clauses = self.applicable_clauses(regions, product)
        out = []
        for vector in vectors:
            scored = sorted(((c, embeddings.cosine(vector, stored[clause_document(c)])) for c in clauses), key=lambda x: -x[1])
            out.append(scored[:k])
        return out

    def recall(self, identity: Identity, vectors: list[list[float]], kinds: list[str], per_query: int, budget: int) -> list[dict]:
        from app.services import memory as memory_service

        stored = self._load_vectors()
        visible = [
            m
            for m in self._memories
            if m["team"] == identity.team
            and identity.role in m["visibility_roles"]
            and m.get("user_email") in (None, identity.email)
            and m["kind"] in kinds
            and m.get("status", "active") == "active"
        ]
        scored = []
        for vector in vectors:
            ranked = sorted(((m, embeddings.cosine(vector, stored[m["text"]])) for m in visible), key=lambda x: -x[1])[:per_query]
            scored += [(memory_service.for_review(m, m["ref"]), score) for m, score in ranked]
        return memory_service.select(scored, budget)


def seed_identity(email: str) -> Identity:
    user = next(u for u in load_seed("users") if u["email"] == email)
    return Identity(user_id=email, email=email, name=user["name"], role=user["role"], team=user["team"])
