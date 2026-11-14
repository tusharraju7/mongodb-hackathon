import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from app.core.codex_cli import CodexModel
from app.core.llm import ModelFailed, TokenUsage, image_block


class Answer(BaseModel):
    ok: bool


def test_structured_image_call_is_isolated_and_counts_tokens(monkeypatch):
    monkeypatch.setattr("app.core.codex_cli.shutil.which", lambda _: "codex.exe")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("MONGODB_URI", "must-not-leak")
    paths = []
    def run(args, **kwargs):
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "MONGODB_URI" not in kwargs["env"]
        assert "--ignore-user-config" in args and "read-only" in args
        assert "features.shell_tool=false" in args
        path = Path(args[args.index("--image") + 1])
        paths.append(path)
        assert path.read_bytes() == b"image"
        Path(args[args.index("--output-last-message") + 1]).write_text('{"ok":true}')
        return SimpleNamespace(returncode=0, stdout=json.dumps({"type":"turn.completed", "usage":{"input_tokens":9,"output_tokens":3,"cached_input_tokens":2}}))
    monkeypatch.setattr("app.core.codex_cli.subprocess.run", run)
    usage = TokenUsage()
    result = CodexModel("test", "low").call(Answer, system="task", user=[image_block(b"image", "image/png")], label="test", usage=usage)
    assert result.ok and usage.as_dict() == {"in":9,"out":3,"cached":2}
    assert not paths[0].exists()


@pytest.mark.parametrize("failure", ["timeout", "invalid", "exit"])
def test_failures_return_no_verdict(monkeypatch, failure):
    monkeypatch.setattr("app.core.codex_cli.shutil.which", lambda _: "codex.exe")
    def run(args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 180)
        Path(args[args.index("--output-last-message") + 1]).write_text("not json")
        return SimpleNamespace(returncode=1 if failure == "exit" else 0, stdout="")
    monkeypatch.setattr("app.core.codex_cli.subprocess.run", run)
    with pytest.raises(ModelFailed):
        CodexModel("test", "low").call(Answer, system="task", user="data", label="test")
