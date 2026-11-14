"""Review sources backed by MongoDB Atlas. The counterpart of fixture_sources.SeedSources."""
from __future__ import annotations

from typing import Optional

from app.models import Identity
from app.services import fundamentals, memory, offers


class MongoSources:
    def __init__(self, db=None):
        self._db = db

    def offer(self, offer_id: str) -> Optional[dict]:
        return offers.get(offer_id, self._db)

    def applicable_clauses(self, regions: list[str], product: str) -> list[dict]:
        return fundamentals.applicable(regions, product, self._db)

    def similar_clauses(self, vectors: list[list[float]], regions: list[str], product: str, k: int) -> list[list[tuple[dict, float]]]:
        return fundamentals.similar(vectors, regions, product, k, self._db)

    def recall(self, identity: Identity, vector: list[float], kinds: list[str], k: int) -> list[dict]:
        return memory.recall_by_vector(identity, vector, kinds, k, self._db)
