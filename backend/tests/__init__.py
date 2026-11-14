"""Offline tests run on the earlier fictional-bank fixtures, which exercise every code path of the engine."""
import os
from pathlib import Path

os.environ["GREENLIGHT_SEED_DIR"] = str(Path(__file__).parent / "fixtures" / "tamarack")
