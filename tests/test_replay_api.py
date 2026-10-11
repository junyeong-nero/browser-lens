import json

from fastapi.testclient import TestClient

from ui import replay
from ui.c3_browser_lens.server import app


def _make_session(base, session_id="20260428-101500", *, with_events=True):
    session = base / session_id
    (session / "history").mkdir(parents=True)
    (session / "video").mkdir()
    (session / "session.json").write_text(
        json.dumps({"query": "search stuff", "model_name": "model-x", "started_at": "2026-04-28T10:15:00"}),
        encoding="utf-8",
    )
    (session / "history" / "step-0001.json").write_text(json.dumps({"step": 1, "url": "https://example.com"}), encoding="utf-8")
    (session / "history" / "step-0001.png").write_bytes(b"png")
    (session / "history" / "step-0001-action.mp4").write_bytes(b"mp4")
    (session / "video" / "session.webm").write_bytes(b"webm")
    if with_events:
        (session / "events.jsonl").write_text(json.dumps({"type": "task_started", "query": "search stuff"}) + "\n", encoding="utf-8")
    return session


def _make_zero_step_session(base, session_id, *, query="unknown task", events=None):
    session = base / session_id
    session.mkdir(parents=True)
    (session / "session.json").write_text(json.dumps({"query": query}), encoding="utf-8")
    if events is not None:
        (session / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
    return session


def test_replay_api_lists_sessions_and_serves_events_and_artifacts(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    _make_session(tmp_path)
    client = TestClient(app)

    sessions = client.get("/sessions")
    assert sessions.status_code == 200
    session = sessions.json()["sessions"][0]
    assert session["id"] == "20260428-101500"
    assert session["query"] == "search stuff"
    assert session["model"] == "model-x"
    assert session["step_count"] == 1
    assert session["has_events"] is True
    assert session["video"] == "video/session.webm"

    events = client.get("/sessions/20260428-101500/events")
    assert events.status_code == 200
    assert events.headers["cache-control"] == "no-store"
    assert events.json()["events"] == [{"type": "task_started", "query": "search stuff"}]

    artifact = client.get("/sessions/20260428-101500/artifacts/history/step-0001.png")
    assert artifact.status_code == 200
    assert artifact.content == b"png"
    assert "max-age=3600" in artifact.headers["cache-control"]

    action_video = client.get("/sessions/20260428-101500/artifacts/history/step-0001-action.mp4")
    assert action_video.status_code == 200
    assert action_video.content == b"mp4"

    llm_trace = replay.logs_history_dir() / "20260428-101500" / "history" / "step-0001-llm.json"
    llm_trace.write_text(json.dumps({"raw_context": {"model": "model-x"}}), encoding="utf-8")
    trace_response = client.get("/sessions/20260428-101500/artifacts/history/step-0001-llm.json")
    assert trace_response.status_code == 200
    assert trace_response.json()["raw_context"]["model"] == "model-x"
    assert client.get("/sessions").json()["sessions"][0]["step_count"] == 1


def test_replay_api_lists_sessions_by_log_name_descending(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    _make_session(tmp_path, "20260614-000006")
    _make_session(tmp_path, "20260615-000001")
    _make_session(tmp_path, "20260615-000004")
    client = TestClient(app)

    sessions = client.get("/sessions").json()["sessions"]

    assert [session["id"] for session in sessions] == [
        "20260615-000004",
        "20260615-000001",
        "20260614-000006",
    ]


def test_replay_api_does_not_expose_backend_trajectory_endpoints(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    _make_session(tmp_path)
    client = TestClient(app)

    for path in ("graph", "cues", "identity-policy", "transitions"):
        assert client.get(f"/sessions/20260428-101500/{path}").status_code == 404


def test_replay_api_rejects_bad_ids_and_path_traversal(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    _make_session(tmp_path)
    client = TestClient(app)

    assert client.get("/sessions/bad-id/events").status_code == 400
    assert client.get("/sessions/20260428-101500/artifacts/../session.json").status_code in {400, 404}
    assert client.get("/sessions/20260428-101500/artifacts/session.json").status_code == 404


def test_replay_api_omits_zero_step_sessions_without_meaningful_events(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    _make_zero_step_session(tmp_path, "20260428-101500")
    _make_zero_step_session(tmp_path, "20260428-101501", events=[])
    _make_zero_step_session(
        tmp_path,
        "20260428-101502",
        query="failed task",
        events=[{"type": "task_failed", "query": "failed task", "error_message": "boom"}],
    )
    client = TestClient(app)

    sessions = client.get("/sessions").json()["sessions"]
    ids = {session["id"] for session in sessions}

    assert "20260428-101500" not in ids
    assert "20260428-101501" not in ids
    assert "20260428-101502" in ids
    failed = next(session for session in sessions if session["id"] == "20260428-101502")
    assert failed["step_count"] == 0
    assert failed["has_events"] is True


def test_replay_api_falls_back_to_synthetic_events(tmp_path):
    replay.set_logs_history_dir(tmp_path)
    session = _make_session(tmp_path, with_events=False)
    (session / "events.jsonl").write_text("", encoding="utf-8")
    (session / "actions.jsonl").write_text(json.dumps({"tool": "navigate", "args": {"url": "https://example.com"}}) + "\n", encoding="utf-8")
    (session / "history" / "step-0001-llm.json").write_text(
        json.dumps({"step": 1, "raw_context": {"model": "model-x"}}),
        encoding="utf-8",
    )
    client = TestClient(app)

    listed = client.get("/sessions").json()["sessions"][0]
    events = client.get("/sessions/20260428-101500/events").json()["events"]

    assert listed["id"] == "20260428-101500"
    assert listed["step_count"] == 1
    assert listed["has_events"] is False
    assert events[0]["type"] == "task_started"
    assert any(event["type"] == "function_calls_extracted" for event in events)
    assert [event["step_id"] for event in events if event["type"] == "action_executed"] == [1]
    assert (session / "events.jsonl.synthetic").exists()
