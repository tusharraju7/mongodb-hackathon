"""Review sources backed by MongoDB Atlas. The counterpart of fixture_sources.SeedSources."""
from __future__ import annotations

from typing import Optional

from app.core import gate
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
        ranked = fundamentals.similar(vectors, regions, product, k, self._db)
        best: dict[str, float] = {}
        for hits in ranked:
            for clause, score in hits:
                best[clause["key"]] = max(best.get(clause["key"], 0.0), score)
        gate.emit("retrieval", "fundamentals.search", params={"collection": "fundamentals", "filter": {"region": regions, "product": product, "status": "approved"}, "queries": len(vectors), "limit": k},
                  result={"status": "ok", "summary": f"{len(best)} clause(s) matched by meaning", "hits": [{"id": key, "score": round(score, 4)} for key, score in sorted(best.items(), key=lambda x: -x[1])]})
        return ranked

    def recall(self, identity: Identity, vectors: list[list[float]], kinds: list[str], per_query: int, budget: int) -> list[dict]:
        chosen = memory.recall_many(identity, vectors, kinds, per_query, budget, self._db)
        gate.emit("retrieval", "memory.recall", params={"collection": "memories", "filter": {"scope.team": identity.team, "visibility_roles": identity.role, "status": "active", "kind": kinds}, "queries": len(vectors)},
                  result={"status": "ok", "summary": f"{len(chosen)} memor{'y' if len(chosen) == 1 else 'ies'} in scope and in view",
                          "hits": [{"id": m["id"], "standing": m["authority"], "strength": m.get("strength")} for m in chosen]})
        return chosen
