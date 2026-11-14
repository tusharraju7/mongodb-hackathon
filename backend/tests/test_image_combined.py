from app.core import llm
from app.services import media


def test_combined_reading_filters_ungrounded_claims(monkeypatch):
    calls=[]
    def respond(model,schema,**kw):
        calls.append(kw["label"])
        return schema.model_validate({"text":"Set your limits", "visual_notes":"A plain banner", "fine_print_present":False,
          "fine_print_legible":True,"people_present":False,
          "extraction":{"claims":[{"type":"other","quote":"Set your limits"},{"type":"other","quote":"invented"}],
          "cta":"Set your limits","tone":"calm","language":"en","description":"Limits banner","summary":"Limits banner"}})
    monkeypatch.setattr(llm,"call_structured",respond)
    result=media.read_image_and_claims(b"pixels","image/png",{"channel":"social"})
    assert calls==["read_image_and_claims"]
    assert [c["quote"] for c in result["extraction"]["claims"]]==["Set your limits"]
