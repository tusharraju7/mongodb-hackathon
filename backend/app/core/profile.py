"""The data set's profile: who the advertiser is, what kinds of claim its ads make, how its banners look.

Everything domain-specific lives in `<seed dir>/profile.json`, so the engine itself stays the same
whether it reviews sportsbook ads or credit card ads.
"""
from __future__ import annotations

import json
from functools import lru_cache

from app.core.config import SEED_DIR

DEFAULTS = {
    "brand": "the company",
    "description": "a company advertising a regulated product",
    "product": "product",
    "region": "CA",
    "teams": [],
    "claim_types": {},
    "memory": {"per_query": 3, "budget": 3},
    "banner": {"header": None, "background": [16, 60, 44], "text": [245, 241, 230], "accent": [214, 178, 94], "headline": "first"},
    "fine_print_patterns": [],
    "decision_labels": {"pass": "approved", "needs_changes": "approved_with_changes", "blocked": "rejected"},
}


@lru_cache
def get_profile() -> dict:
    path = SEED_DIR / "profile.json"
    loaded = json.loads(path.read_text()) if path.exists() else {}
    return {**DEFAULTS, **loaded}


def claim_types() -> list[str]:
    return list(get_profile()["claim_types"]) + ["other"]
