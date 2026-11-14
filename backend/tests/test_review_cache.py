from app.core.review_cache import Cache
from app.services.compliance import _cache_key

def test_cache_expiry_eviction_and_copy_isolation(monkeypatch):
    clock=[0]
    monkeypatch.setattr("app.core.review_cache.time.monotonic",lambda:clock[0])
    c=Cache(capacity=1,ttl=10)
    c.put("a",{"x":[]})
    c.get("a")["x"].append("mutation")
    assert c.get("a")=={"x":[]}
    c.put("b",{})
    assert c.get("a") is None
    clock[0]=11
    assert c.get("b") is None

def test_review_key_invalidates_material_inputs_and_scope(people):
    import copy
    base=dict(text="Ad",offer={"version":1,"terms":"old"},clauses=[{"key":"R1","version":1,"text":"old"}],
       memories=[{"id":"m1","text":"old","authority":"binding"}],ctx={"channel":"email","fine_print_legible":True},identity=people["marketer"])
    original=_cache_key(**base)
    variants=[]
    for group,field,value in [("offer","terms","new"),("ctx","channel","social"),("ctx","fine_print_legible",False)]:
        v=copy.deepcopy(base);v[group][field]=value;variants.append(v)
    for group in ("clauses","memories"):
        v=copy.deepcopy(base);v[group][0]["text"]="changed without a version bump";variants.append(v)
    for changes in ({"identity":people["manager"]},{"memories":[]},{"use_memory":False},{"text":"Edited ad"}):
        variants.append({**base,**changes})
    assert all(_cache_key(**v)!=original for v in variants)
