from app.core import llm

def test_openai_content_preserves_text_and_converts_image():
    blocks = [{"type":"text","text":"Policy","cache_control":{"type":"ephemeral"}}, llm.image_block(b"image", "image/png")]
    converted = llm.provider_content(blocks, True)
    assert converted[0] == {"type":"text","text":"Policy"}
    assert converted[1]["image_url"]["url"] == "data:image/png;base64,aW1hZ2U="
    assert "cache_control" in blocks[0]
    assert llm.provider_content(blocks, False) is blocks

def test_openai_model_uses_responses(monkeypatch):
    import langchain_openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-a-real-key")
    calls=[]
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: calls.append(kw) or kw)
    llm.build_model("openai:gpt-5.4-mini", "low")
    assert calls[0]["use_responses_api"] is True
    assert calls[0]["reasoning"] == {"effort":"low"}
    assert "output_config" not in calls[0]
    assert calls[0]["store"] is False

def test_anthropic_baseline_remains_supported(monkeypatch):
    calls=[]
    monkeypatch.setattr(llm, "init_chat_model", lambda name, **kw: calls.append((name,kw)))
    llm.build_model("anthropic:claude-opus-5-5", "low")
    assert calls[0][1]["output_config"] == {"effort":"low"}

def test_chat_history_is_namespaced_per_authenticated_user(people):
    from app.agent.graph import read_history
    from types import SimpleNamespace
    class Graph:
        def get_state(self, config):
            return SimpleNamespace(values={"history":[{"text":config["configurable"]["thread_id"]}]})
    user=read_history(people['marketer'], 'project-same', Graph())
    lawyer=read_history(people['manager'], 'project-same', Graph())
    assert user != lawyer
    assert user[0]['text'].startswith(people['marketer'].user_id+':')
