"""An in-memory database loaded from backend/seed, with embeddings faked. No network."""
import json
from datetime import datetime, timezone

import mongomock
import pytest

from app.core import embeddings, security
from app.core.config import SEED_DIR
from app.models import Identity

PASSWORD = "correct horse battery"


def _date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _seed(name):
    return json.loads((SEED_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    """Vectors are not compared in these tests, so any fixed-size vector will do."""
    fake = lambda texts: [[0.0] * 8 for _ in texts]
    monkeypatch.setattr(embeddings, "embed_documents", fake)
    monkeypatch.setattr(embeddings, "embed_queries", fake)


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True).greenlight
    now = datetime.now(timezone.utc)
    database.policies.insert_many(_seed("policies"))
    password_hash = security.hash_password(PASSWORD)
    for u in _seed("users"):
        database.users.insert_one({"_id": u["email"], **u, "password_hash": password_hash, "created_at": now})
    for o in _seed("offers"):
        database.offers.insert_one({**o, "valid_from": _date(o["valid_from"]), "valid_to": _date(o["valid_to"])})
    for c in _seed("fundamentals"):
        c.pop("previous_texts", None)
        database.fundamentals.insert_one({**c, "effective_from": _date(c["effective_from"]), "effective_to": _date(c.get("effective_to")), "embedding": [0.0] * 8, "updated_at": now})
    return database


def who(email: str) -> Identity:
    user = next(u for u in _seed("users") if u["email"] == email)
    return Identity(user_id=email, email=email, name=user["name"], role=user["role"], team=user["team"])


@pytest.fixture
def people():
    return {
        "manager": who("manager.national@tamarack.test"),
        "marketer": who("marketer.national@tamarack.test"),
        "sales": who("sales.national@tamarack.test"),
        "qc_manager": who("manager.quebec@tamarack.test"),
        "qc_marketer": who("marketer.quebec@tamarack.test"),
    }

@pytest.fixture(autouse=True)
def offline_model_factories(monkeypatch):
    # Flow tests stub call_structured; constructing a provider client first
    # must not require real credentials from the developer's environment.
    from app.core import llm
    monkeypatch.setattr(llm, "main_model", lambda: object())
    monkeypatch.setattr(llm, "fast_model", lambda: object())

@pytest.fixture(autouse=True)
def clear_review_caches():
    from app.core import review_cache
    for cache in (review_cache.readings,review_cache.extractions,review_cache.reports):cache.clear()
    yield
    for cache in (review_cache.readings,review_cache.extractions,review_cache.reports):cache.clear()
