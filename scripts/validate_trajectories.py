from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TERMINAL_EVENT_TYPES = {"task_complete", "task_failed", "task_interrupted"}
KEEP_TERMINAL_TYPES = {"task_complete", "task_failed"}
DEFAULT_HISTORY_DIR = Path(__file__).resolve().parents[1] / "logs" / "history"

ClassificationKind = Literal["KEEP", "REJECT", "SKIP"]


@dataclass(frozen=True)
class TrajectoryClassification:
    session_dir: Path
    kind: ClassificationKind
    reason: str
    query: str | None = None


def _has_any_files(session_dir: Path) -> bool:
    return any(path.is_file() for path in session_dir.rglob("*"))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_event_types(path: Path) -> list[str]:
    event_types: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return event_types
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            event_types.append(value["type"])
    return event_types


def classify_session_dir(session_dir: Path) -> TrajectoryClassification:
    """Classify one logs/history/<timestamp> directory."""
    session_dir = Path(session_dir)
    if not _has_any_files(session_dir):
        return TrajectoryClassification(session_dir=session_dir, kind="SKIP", reason="empty")

    session_path = session_dir / "session.json"
    if not session_path.is_file():
        return TrajectoryClassification(session_dir=session_dir, kind="SKIP", reason="empty")

    session_meta = _read_json(session_path)
    query = session_meta.get("query")
    model_name = session_meta.get("model_name") or session_meta.get("model")
    if query == "test_query" or model_name == "test_model":
        return TrajectoryClassification(
            session_dir=session_dir,
            kind="SKIP",
            reason="test",
            query=query if isinstance(query, str) else None,
        )

    terminal_events = [
        event_type
        for event_type in _read_event_types(session_dir / "events.jsonl")
        if event_type in TERMINAL_EVENT_TYPES
    ]
    query_value = query if isinstance(query, str) else None
    if not terminal_events:
        return TrajectoryClassification(
            session_dir=session_dir,
            kind="REJECT",
            reason="incomplete/killed",
            query=query_value,
        )

    last_terminal = terminal_events[-1]
    if last_terminal in KEEP_TERMINAL_TYPES:
        return TrajectoryClassification(
            session_dir=session_dir,
            kind="KEEP",
            reason="natural_terminal",
            query=query_value,
        )
    return TrajectoryClassification(
        session_dir=session_dir,
        kind="REJECT",
        reason="interrupted",
        query=query_value,
    )


def _scan_history(history_dir: Path) -> list[TrajectoryClassification]:
    if not history_dir.is_dir():
        return []
    return [
        classify_session_dir(path)
        for path in sorted(history_dir.iterdir())
        if path.is_dir()
    ]


def _print_summary(results: list[TrajectoryClassification]) -> None:
    counts = {
        "KEEP": 0,
        "REJECT-interrupted": 0,
        "REJECT-incomplete": 0,
        "SKIP-test": 0,
        "SKIP-empty": 0,
    }
    for result in results:
        if result.kind == "KEEP":
            counts["KEEP"] += 1
        elif result.kind == "REJECT" and result.reason == "interrupted":
            counts["REJECT-interrupted"] += 1
        elif result.kind == "REJECT":
            counts["REJECT-incomplete"] += 1
        elif result.reason == "test":
            counts["SKIP-test"] += 1
        else:
            counts["SKIP-empty"] += 1

    for label, count in counts.items():
        print(f"{label}: {count}")

    for result in results:
        if result.kind != "REJECT":
            continue
        query = result.query or "(unknown query)"
        print(f"REJECT {result.session_dir.name}: {query} [{result.reason}]")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate BrowserLens trajectory log completeness.",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=DEFAULT_HISTORY_DIR,
        help="logs/history directory to scan. Defaults to the repository logs/history.",
    )
    parser.add_argument(
        "--list-rerun",
        action="store_true",
        help="Print only rejected real-task queries, one per line.",
    )
    args = parser.parse_args()

    results = _scan_history(args.history_dir)
    if args.list_rerun:
        for result in results:
            if result.kind == "REJECT" and result.query:
                print(result.query)
        return 0

    _print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
