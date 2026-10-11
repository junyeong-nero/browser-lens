import argparse
import importlib
import sys
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.actor import BrowserAgent
from agents.planner import PlannerAgent
from browser import ArtifactLogger, PlaywrightBrowser
import config as app_config
from core.types import GroundingMode, Subgoal
from task_events import (
    build_session_metadata,
    build_task_complete_event,
    build_task_failed_event_from_result,
    result_status,
)
from ui.bridge import emit, register_event_sink, unregister_event_sink


PLAYWRIGHT_SCREEN_SIZE = (1600, 900)
LOGS_DIR = Path(__file__).resolve().parent / "logs" / "history"
DEFAULT_UI_CONDITION = "c3_browser_lens"
UI_CONDITION_MODULES = {
    "c1_simple_ui": "ui.c1_simple_ui.server",
    "c2_browser_lens_no_graph": "ui.c2_browser_lens_no_graph.server",
    "c3_browser_lens": "ui.c3_browser_lens.server",
}
UI_CONDITION_ALIASES = {
    "c1": "c1_simple_ui",
    "c1_simple_ui": "c1_simple_ui",
    "simple_ui": "c1_simple_ui",
    "c2": "c2_browser_lens_no_graph",
    "c2_browser_lens_no_graph": "c2_browser_lens_no_graph",
    "browser_lens_no_graph": "c2_browser_lens_no_graph",
    "browserlens_no_graph": "c2_browser_lens_no_graph",
    "no_graph": "c2_browser_lens_no_graph",
    "c3": "c3_browser_lens",
    "c3_browser_lens": "c3_browser_lens",
    "browser_lens": "c3_browser_lens",
    "browserlens": "c3_browser_lens",
}


def _parse_proxy(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        raise argparse.ArgumentTypeError(
            f"--proxy must be scheme://[user:pass@]host[:port], got: {value}"
        )
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected True or False.")


def parse_screen_size(value: str) -> tuple[int, int] | None:
    """Parse WIDTHxHEIGHT screen sizes; ``auto`` means detect at runtime."""
    normalized = value.strip().lower()
    if normalized == "auto":
        return None
    separator = "x" if "x" in normalized else "×"
    try:
        width_text, height_text = normalized.split(separator, 1)
        width = int(width_text)
        height = int(height_text)
    except (ValueError, AttributeError) as exc:
        raise argparse.ArgumentTypeError("Expected WIDTHxHEIGHT or auto.") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Screen size must be positive.")
    return width, height


def parse_ui_condition(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    condition = UI_CONDITION_ALIASES.get(normalized)
    if condition is None:
        valid = ", ".join(("c1", "c2", "c3"))
        raise argparse.ArgumentTypeError(f"Expected one of: {valid}.")
    return condition


def detect_screen_size() -> tuple[int, int] | None:
    """Return the current desktop's logical screen size, if available."""
    try:
        import tkinter
    except Exception:
        return None

    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
    except Exception:
        return None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    if width <= 0 or height <= 0:
        return None
    return width, height


def resolve_screen_size(screen_size: tuple[int, int] | None) -> tuple[int, int]:
    if screen_size is not None:
        return screen_size
    detected = detect_screen_size()
    if detected is not None:
        return detected
    return PLAYWRIGHT_SCREEN_SIZE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the browser agent with a query.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "query",
        type=str,
        nargs="?",
        default=None,
        help="The query for the browser agent to execute. Omit it to start the UI.",
    )
    parser.add_argument(
        "--ui-condition",
        type=parse_ui_condition,
        default=None,
        metavar="{c1,c2,c3}",
        help=(
            "UI experiment condition used when query is omitted: "
            "c1=simple UI, c2=BrowserLens without graph, c3=BrowserLens. "
            "Defaults to c3."
        ),
    )
    parser.add_argument(
        "--env",
        type=str,
        choices=("playwright",),
        default="playwright",
        help="The browser environment to use.",
    )
    parser.add_argument(
        "--initial_url",
        type=str,
        default="https://www.duckduckgo.com",
        help="The initial URL loaded in the browser.",
    )
    parser.add_argument(
        "--search_engine_url",
        type=str,
        default="https://www.duckduckgo.com",
        help="The URL opened when the agent uses the search tool.",
    )
    parser.add_argument(
        "--highlight_mouse",
        action="store_true",
        default=False,
        help="If possible, highlight clicked targets and pointer locations.",
    )
    parser.add_argument(
        "--headless",
        type=parse_bool,
        default=False,
        help="Whether to launch Playwright in headless mode. Use True or False.",
    )
    parser.add_argument(
        "--screen-size",
        type=parse_screen_size,
        default=None,
        help=(
            "Browser screen size as WIDTHxHEIGHT, or auto to use the current "
            f"display size. Defaults to auto; fallback is {PLAYWRIGHT_SCREEN_SIZE[0]}x{PLAYWRIGHT_SCREEN_SIZE[1]}."
        ),
    )
    parser.add_argument(
        "--log",
        action="store_true",
        default=False,
        help="Save per-step DOM/screenshot/GIF history plus JSON action trajectory under logs/history/.",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        default=False,
        help="Save Playwright .webm and session_60fps.mp4 video under logs/history/<timestamp>/video/.",
    )
    parser.add_argument(
        "--model",
        default=app_config.actor_model(),
        help="Set which main model to use.",
    )
    parser.add_argument(
        "--grounding",
        choices=["vision", "text", "mixed"],
        default="text",
        help=(
            "Page grounding mode: vision (screenshot+coords), "
            "text (ARIA snapshot+refs), or mixed (both). "
            "Note: 'text' mode requires a standard function-calling model, not computer-use."
        ),
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        default=False,
        help="Inject anti-automation patches (navigator.webdriver, plugins, languages, WebGL vendor).",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Playwright browser channel (e.g. 'chrome', 'msedge'). Requires `playwright install <channel>`.",
    )
    parser.add_argument(
        "--locale",
        default=None,
        help="Browser locale, e.g. ko-KR.",
    )
    parser.add_argument(
        "--timezone",
        dest="timezone_id",
        default=None,
        help="IANA timezone id, e.g. Asia/Seoul.",
    )
    parser.add_argument(
        "--user-agent",
        dest="user_agent",
        default=None,
        help="Override the browser User-Agent string.",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy URL: scheme://[user:pass@]host:port.",
    )
    parser.add_argument(
        "--storage-state",
        dest="storage_state",
        default=None,
        help="Path to a Playwright storage_state JSON. Loaded on start, saved on exit.",
    )
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    ui_condition = getattr(args, "ui_condition", None)
    if args.query and ui_condition is not None:
        parser.error("--ui-condition is only used when the positional query is omitted.")
    if ui_condition is None:
        args.ui_condition = DEFAULT_UI_CONDITION


def _create_artifact_logger(*, log_enabled: bool, video_enabled: bool) -> ArtifactLogger:
    log_dir = (
        str(LOGS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S"))
        if log_enabled or video_enabled
        else None
    )
    return ArtifactLogger(
        log_dir=log_dir,
        history_enabled=log_enabled,
        video_enabled=video_enabled,
    )


def _create_playwright_browser(
    args: argparse.Namespace,
    artifact_logger: ArtifactLogger,
) -> PlaywrightBrowser:
    return PlaywrightBrowser(
        screen_size=resolve_screen_size(args.screen_size),
        initial_url=args.initial_url,
        search_engine_url=args.search_engine_url,
        highlight_mouse=args.highlight_mouse,
        headless=args.headless,
        fit_window_to_screen=not args.headless,
        artifact_logger=artifact_logger,
        channel=args.channel,
        user_agent=args.user_agent,
        locale=args.locale,
        timezone_id=args.timezone_id,
        proxy=_parse_proxy(args.proxy),
        storage_state_path=args.storage_state,
        stealth=args.stealth,
    )


def _session_metadata(
    args: argparse.Namespace,
    execution_constraints: Any,
) -> dict[str, Any]:
    return build_session_metadata(
        query=args.query,
        model_name=args.model,
        grounding=args.grounding,
        started_at=datetime.now(),
        use_planner=True,
        video_enabled=args.video,
        constraints=execution_constraints,
    )


def _plan_subgoals(
    args: argparse.Namespace,
) -> tuple[
    list[Subgoal] | None,
    Callable[[Subgoal, str, list[Subgoal]], list[Subgoal]] | None,
]:
    planner_kwargs: dict[str, Any] = {"query": args.query}
    if args.log:
        planner_kwargs["event_sink"] = emit
    planner = PlannerAgent(**planner_kwargs)
    subgoals = planner.plan()
    if not subgoals:
        emit({"type": "planner_fallback", "reason": "no valid subgoals returned"})
        return None, None

    print(f"Planner created {len(subgoals)} subgoal(s):")
    for subgoal in subgoals:
        print(f"  [{subgoal.id}] {subgoal.description}")
    return subgoals, planner.replan


def _run_cli_mode(
    browser_computer: PlaywrightBrowser,
    args: argparse.Namespace,
    artifact_logger: ArtifactLogger,
) -> None:
    execution_constraints = app_config.execution_constraints()
    if args.log:
        artifact_logger.record_session_meta(_session_metadata(args, execution_constraints))
        register_event_sink(artifact_logger.record_event)

    emit({"type": "task_started", "query": args.query})
    failure_emitted = False
    try:
        subgoals, replan_callback = _plan_subgoals(args)
        grounding: GroundingMode = args.grounding
        agent = BrowserAgent(
            browser_computer=browser_computer,
            query=args.query,
            model_name=args.model,
            event_sink=emit if args.log else None,
            artifact_logger=artifact_logger,
            grounding=grounding,
            subgoals=subgoals,
            replan_callback=replan_callback,
            max_steps_per_subgoal=execution_constraints.max_steps_per_subgoal,
            max_total_steps=execution_constraints.max_total_steps,
            max_subgoals=execution_constraints.max_subgoals,
        )
        result = agent.agent_loop()
        status = result_status(result)
        if status != "complete":
            failure_event = build_task_failed_event_from_result(
                query=args.query,
                result=result,
            )
            emit(failure_event)
            failure_emitted = True
            failure_reason = getattr(result, "reason", None) or getattr(
                result, "summary", None
            )
            raise RuntimeError(
                failure_reason or f"Task ended with status {status}"
            )
        emit(build_task_complete_event(query=args.query, agent=agent, result=result))
    except Exception as exc:
        if not failure_emitted:
            emit({"type": "task_failed", "query": args.query, "status": "failed", "error_message": str(exc)})
        raise
    finally:
        if args.log:
            unregister_event_sink(artifact_logger.record_event)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    artifact_logger = _create_artifact_logger(
        log_enabled=args.log,
        video_enabled=args.video,
    )
    env = _create_playwright_browser(args, artifact_logger)

    with env as browser_computer:
        if args.query is None:
            _run_ui_mode(browser_computer, args)
        else:
            _run_cli_mode(browser_computer, args, artifact_logger)
    return 0


def _run_ui_mode(browser_computer: PlaywrightBrowser, args: argparse.Namespace) -> None:
    from session import BrowserSession

    ui_condition = parse_ui_condition(
        getattr(args, "ui_condition", None) or DEFAULT_UI_CONDITION
    )
    server_module = UI_CONDITION_MODULES[ui_condition]
    _ui_server = importlib.import_module(server_module)

    ready = threading.Event()
    server_thread = threading.Thread(
        target=_ui_server.start,
        kwargs={"on_ready": ready},
        daemon=True,
        name="ui-server",
    )
    server_thread.start()

    if not ready.wait(timeout=10):
        print("Warning: UI server did not start in time.")

    url = f"http://{_ui_server.HOST}:{_ui_server.port}"
    print(f"Panel: {url}")
    webbrowser.open(url)

    session = BrowserSession(
        browser_computer=browser_computer,
        model_name=args.model,
        logs_dir=LOGS_DIR,
        log_enabled=args.log,
        video_enabled=args.video,
        grounding=args.grounding,
        use_planner=True,
    )
    session.run()


if __name__ == "__main__":
    raise SystemExit(main())
