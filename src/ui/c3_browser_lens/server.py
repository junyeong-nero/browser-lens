"""FastAPI server for the full browser-agent control panel."""
import threading
from pathlib import Path

from ui.bridge import task_queue
from ui.server_core import (
    DEFAULT_PORT,
    HOST,
    PORT_RANGE,
    create_panel_app,
    find_free_port,
    run_panel_server,
)

_UI_DIR = Path(__file__).parent
_STATIC_ASSET_NAMES = (
    "panel.css",
    "graph/graph-state.js",
    "graph/graph-artifacts.js",
    "graph/graph-noop-evidence.js",
    "graph/graph-right-panel.js",
    "graph/graph-cues.js",
    "graph/graph-build.js",
    "graph/graph-selection.js",
    "graph/graph-layout.js",
    "graph/graph-tooltip.js",
    "graph/graph-render.js",
)
_SHARED_STATIC_ASSET_NAMES = (
    "panel/panel-state.js",
    "panel/panel-timeline.js",
    "panel/panel-sidebar.js",
    "panel/panel-stats-data.js",
    "panel/panel-stats-render.js",
    "panel/panel-events.js",
    "panel/panel-markdown.js",
    "panel/panel-replay.js",
    "panel/panel-input.js",
)

# Resolved port, set by start() before returning.
port: int = DEFAULT_PORT

app = create_panel_app(
    ui_dir=_UI_DIR,
    static_asset_names=_STATIC_ASSET_NAMES,
    shared_static_asset_names=_SHARED_STATIC_ASSET_NAMES,
    task_queue_getter=lambda: task_queue,
)


def start(on_ready: threading.Event | None = None) -> None:
    """Run uvicorn. Call in a daemon thread. Sets module-level `port` before signalling ready."""
    global port
    port = find_free_port(DEFAULT_PORT, PORT_RANGE)
    run_panel_server(app, port=port, on_ready=on_ready)
