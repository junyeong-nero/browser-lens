import pytest


@pytest.fixture(autouse=True)
def isolate_logs_history_dir(tmp_path, monkeypatch):
    from ui import replay
    import main

    original_replay_dir = replay.logs_history_dir()
    original_main_logs_dir = main.LOGS_DIR
    test_history_dir = tmp_path / "logs" / "history"

    replay.set_logs_history_dir(test_history_dir)
    monkeypatch.setattr(main, "LOGS_DIR", test_history_dir)
    try:
        yield
    finally:
        replay.set_logs_history_dir(original_replay_dir)
        monkeypatch.setattr(main, "LOGS_DIR", original_main_logs_dir)
