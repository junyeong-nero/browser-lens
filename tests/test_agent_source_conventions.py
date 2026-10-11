from pathlib import Path


def test_actor_agent_uses_project_header_convention():
    source = Path("src/agents/actor/agent.py").read_text(encoding="utf-8")
    header = "\n".join(source.splitlines()[:14])

    assert "Copyright 2025 Google LLC" not in header
    assert "Licensed under the Apache License" not in header
