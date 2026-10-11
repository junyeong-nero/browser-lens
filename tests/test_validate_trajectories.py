import json
from pathlib import Path

from scripts.validate_trajectories import classify_session_dir


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_events(path: Path, event_types: list[str]) -> None:
    path.write_text(
        "".join(json.dumps({"type": event_type}) + "\n" for event_type in event_types),
        encoding="utf-8",
    )


def test_classify_keeps_natural_terminal_session(tmp_path):
    _write_json(tmp_path / "session.json", {"query": "real task", "model_name": "real_model"})
    _write_events(tmp_path / "events.jsonl", ["task_started", "task_failed"])

    result = classify_session_dir(tmp_path)

    assert result.kind == "KEEP"
    assert result.reason == "natural_terminal"
    assert result.query == "real task"


def test_classify_rejects_interrupted_session(tmp_path):
    _write_json(tmp_path / "session.json", {"query": "real task", "model_name": "real_model"})
    _write_events(tmp_path / "events.jsonl", ["task_started", "task_interrupted"])

    result = classify_session_dir(tmp_path)

    assert result.kind == "REJECT"
    assert result.reason == "interrupted"
    assert result.query == "real task"


def test_classify_rejects_session_without_terminal_event(tmp_path):
    _write_json(tmp_path / "session.json", {"query": "real task", "model_name": "real_model"})
    _write_events(tmp_path / "events.jsonl", ["task_started", "step_started"])

    result = classify_session_dir(tmp_path)

    assert result.kind == "REJECT"
    assert result.reason == "incomplete/killed"


def test_classify_skips_test_session(tmp_path):
    _write_json(tmp_path / "session.json", {"query": "test_query", "model_name": "real_model"})
    _write_events(tmp_path / "events.jsonl", ["task_started", "task_failed"])

    result = classify_session_dir(tmp_path)

    assert result.kind == "SKIP"
    assert result.reason == "test"


def test_classify_skips_empty_or_non_session_dirs(tmp_path):
    empty_result = classify_session_dir(tmp_path)

    assert empty_result.kind == "SKIP"
    assert empty_result.reason == "empty"

    non_session = tmp_path / "notes.txt"
    non_session.write_text("not a collection session\n", encoding="utf-8")

    no_session_result = classify_session_dir(tmp_path)

    assert no_session_result.kind == "SKIP"
    assert no_session_result.reason == "empty"
