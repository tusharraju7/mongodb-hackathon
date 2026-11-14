"""Bounded, short-lived process-local reuse. Never stores credentials or persists user media."""
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import threading
import time

class StaleAssessment(Exception):
    """Reviewed inputs changed or the local assessment expired; reassess explicitly."""

VERSION = "combined-review-v1"

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()

def configuration():
    from app.core.config import get_settings
    from app.core.profile import get_profile
    from app.agent import prompts
    s=get_settings()
    return [VERSION,prompts.PROMPT_VERSION,s.llm_model,s.llm_fast_model,s.llm_effort,s.llm_fast_effort,s.voyage_model,get_profile()]

class Cache:
    def __init__(self, capacity=128, ttl=900):
        self.capacity,self.ttl=capacity,ttl
        self.entries=OrderedDict()
        self.lock=threading.Lock()
    def get(self,key):
        with self.lock:
            item=self.entries.get(key)
            if item is None:return None
            if time.monotonic()-item[0]>=self.ttl:
                self.entries.pop(key,None)
                return None
            self.entries.move_to_end(key)
            return deepcopy(item[1])
    def put(self,key,value):
        with self.lock:
            self.entries[key]=(time.monotonic(),deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries)>self.capacity:self.entries.popitem(last=False)
    def clear(self):
        with self.lock:self.entries.clear()

readings=Cache()
extractions=Cache()
reports=Cache()
