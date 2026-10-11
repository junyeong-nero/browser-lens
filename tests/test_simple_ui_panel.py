import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ui.c1_simple_ui.server import app
from ui.bridge import reset_task_state_for_tests


SIMPLE_PANEL_HTML_ONLY = Path("src/ui/c1_simple_ui/panel.html").read_text(encoding="utf-8")


def _read_css_bundle(entrypoint: str) -> str:
    path = Path(entrypoint)
    text = path.read_text(encoding="utf-8")
    imports = re.findall(r'@import url\("([^"]+)"\);', text)
    if not imports:
        return text
    return "\n".join((path.parent / imported).read_text(encoding="utf-8") for imported in imports)


SIMPLE_PANEL_CSS = _read_css_bundle("src/ui/c1_simple_ui/static/panel.css")
SIMPLE_GRAPH_JS = Path("src/ui/c1_simple_ui/static/graph.js").read_text(encoding="utf-8")
_SIMPLE_PANEL_JS_PARTS = (
    "00-state.js",
    "01-connection-timeline.js",
    "02-details-sidebar.js",
    "03-plan-summaries.js",
    "04-main-view-events.js",
    "05-markdown.js",
    "06-replay.js",
    "07-task-resize.js",
)
SIMPLE_PANEL_JS = "\n".join(
    Path(f"src/ui/c1_simple_ui/static/panel/{name}").read_text(encoding="utf-8")
    for name in _SIMPLE_PANEL_JS_PARTS
) + "\n" + Path("src/ui/c1_simple_ui/static/panel.js").read_text(encoding="utf-8")


def test_simple_panel_loads_own_static_assets():
    assert "<title>BrowserLens</title>" in SIMPLE_PANEL_HTML_ONLY
    assert '<span class="title" id="hdr-title">BrowserLens</span>' in SIMPLE_PANEL_HTML_ONLY
    assert '<link rel="stylesheet" href="/static/panel.css">' in SIMPLE_PANEL_HTML_ONLY
    assert '<script src="/static/graph.js"></script>' in SIMPLE_PANEL_HTML_ONLY
    for name in _SIMPLE_PANEL_JS_PARTS:
        assert f'<script src="/static/panel/{name}"></script>' in SIMPLE_PANEL_HTML_ONLY
    assert '<script src="/static/panel.js"></script>' in SIMPLE_PANEL_HTML_ONLY
    assert "d3.v7.min.js" not in SIMPLE_PANEL_HTML_ONLY
    assert '<style>' not in SIMPLE_PANEL_HTML_ONLY
    assert '<script>' not in SIMPLE_PANEL_HTML_ONLY


def test_simple_panel_keeps_full_ui_chrome_and_timeline_surface():
    assert 'class="brand-mark"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="dot"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="status-label"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="theme-toggle"' not in SIMPLE_PANEL_HTML_ONLY
    assert "<span>New</span>" in SIMPLE_PANEL_HTML_ONLY
    assert "<span>History</span>" in SIMPLE_PANEL_HTML_ONLY
    assert 'id="replay-controls"' in SIMPLE_PANEL_HTML_ONLY
    assert 'data-view="timeline"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="timeline"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="input-shell"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="input"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="agent-model"' in SIMPLE_PANEL_HTML_ONLY
    assert "Timeline" in SIMPLE_PANEL_HTML_ONLY

    assert 'id="left-sidebar"' not in SIMPLE_PANEL_HTML_ONLY
    assert 'id="left-resizer"' not in SIMPLE_PANEL_HTML_ONLY
    assert 'id="right-sidebar"' in SIMPLE_PANEL_HTML_ONLY
    assert 'class="side-panel simple-screenshot-panel"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="right-resizer"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="side-step-title"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="side-replay"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="simple-action-details"' in SIMPLE_PANEL_HTML_ONLY
    assert 'data-view="graph"' not in SIMPLE_PANEL_HTML_ONLY
    assert 'id="graph-wrap"' not in SIMPLE_PANEL_HTML_ONLY
    assert 'id="graph-svg"' not in SIMPLE_PANEL_HTML_ONLY


def test_simple_panel_sessions_panel_closes_on_outside_click_and_escape():
    assert "function closeSessionsPanel()" in SIMPLE_PANEL_JS
    assert "function isSessionsPanelTarget(target)" in SIMPLE_PANEL_JS
    assert "document.addEventListener('pointerdown', (event) => {" in SIMPLE_PANEL_JS
    assert "if (isSessionsPanelTarget(event.target)) return;" in SIMPLE_PANEL_JS
    assert "closeSessionsPanel();" in SIMPLE_PANEL_JS
    assert "document.addEventListener('keydown', (event) => {" in SIMPLE_PANEL_JS
    assert "if (event.key === 'Escape') closeSessionsPanel();" in SIMPLE_PANEL_JS


def test_simple_panel_history_drawer_markup_and_state_refs_are_available():
    load_sessions = SIMPLE_PANEL_JS.split("async function loadSessions()", 1)[1].split(
        "function showReplayMessage", 1
    )[0]

    assert 'id="sessions-panel" class="hidden sessions-drawer" role="dialog" aria-label="History"' in SIMPLE_PANEL_HTML_ONLY
    assert 'aria-modal="false"' in SIMPLE_PANEL_HTML_ONLY
    assert 'class="sessions-head-main"' in SIMPLE_PANEL_HTML_ONLY
    assert 'class="sessions-title"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="sessions-summary"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="sessions-search"' in SIMPLE_PANEL_HTML_ONLY
    assert 'class="sessions-message"' in SIMPLE_PANEL_JS
    assert 'Loading saved sessions' in load_sessions
    assert 'loading…' not in load_sessions
    assert 'aria-label="Search history"' in SIMPLE_PANEL_HTML_ONLY
    assert 'placeholder="Search query, session id, or model"' in SIMPLE_PANEL_HTML_ONLY
    assert 'class="sessions-body"' in SIMPLE_PANEL_HTML_ONLY
    assert 'id="sessions-list"' in SIMPLE_PANEL_HTML_ONLY
    assert 'Loading saved sessions' in SIMPLE_PANEL_HTML_ONLY
    assert "const sessionsSearch = document.getElementById('sessions-search');" in SIMPLE_PANEL_JS
    assert "const sessionsSummary = document.getElementById('sessions-summary');" in SIMPLE_PANEL_JS
    assert 'aria-label="Close History"' in SIMPLE_PANEL_HTML_ONLY
    assert 'title="Close History"' in SIMPLE_PANEL_HTML_ONLY


def test_simple_panel_history_drawer_filters_groups_and_renders_query_first_rows():
    load_sessions = SIMPLE_PANEL_JS.split("async function loadSessions()", 1)[1].split(
        "function showReplayMessage", 1
    )[0]

    assert "let savedSessions = [];" in SIMPLE_PANEL_JS
    assert "let sessionsSearchQuery = '';" in SIMPLE_PANEL_JS
    assert "function sessionMatchesSearch(session, query)" in SIMPLE_PANEL_JS
    assert "function compareSessionsByLogNameDesc(left, right)" in SIMPLE_PANEL_JS
    assert "function groupSessionsByDate(sessions)" in SIMPLE_PANEL_JS
    assert "function renderSessions()" in SIMPLE_PANEL_JS
    assert "function updateSessionsSummary(total, visible)" in SIMPLE_PANEL_JS
    assert "session.query || 'unknown task'" in SIMPLE_PANEL_JS
    assert "[session.query, session.id, session.model]" in SIMPLE_PANEL_JS
    assert "sessionsSearch.addEventListener('input'" in SIMPLE_PANEL_JS
    assert "savedSessions = Array.isArray(data.sessions) ? data.sessions : [];" in load_sessions
    assert "renderSessions();" in load_sessions
    assert ".sort(compareSessionsByLogNameDesc)" in SIMPLE_PANEL_JS
    assert 'class="session-primary"' in SIMPLE_PANEL_JS
    assert 'class="session-meta"' in SIMPLE_PANEL_JS
    assert 'class="session-current-marker"' in SIMPLE_PANEL_JS
    assert 'class="session-date-group"' in SIMPLE_PANEL_JS
    assert 'class="session-artifact-badge">events</span>' in SIMPLE_PANEL_JS
    assert 'class="session-artifact-badge">video</span>' in SIMPLE_PANEL_JS
    assert 'class="sessions-message"' in SIMPLE_PANEL_JS
    assert 'No sessions match your search' in SIMPLE_PANEL_JS
    assert 'class="session-date-tag' not in SIMPLE_PANEL_JS
    assert 'class="session-metrics"' not in SIMPLE_PANEL_JS


def test_simple_panel_history_drawer_styles_are_available():
    assert "#sessions-panel.sessions-drawer {" in SIMPLE_PANEL_CSS
    assert "#sessions-panel.sessions-drawer.hidden {" in SIMPLE_PANEL_CSS
    assert ".sessions-search {" in SIMPLE_PANEL_CSS
    assert ".sessions-body {" in SIMPLE_PANEL_CSS
    assert ".sessions-message {" in SIMPLE_PANEL_CSS
    assert ".session-date-group {" in SIMPLE_PANEL_CSS
    assert ".session-date-group h3 {" in SIMPLE_PANEL_CSS
    assert ".session-main-row {" in SIMPLE_PANEL_CSS
    assert ".session-primary {" in SIMPLE_PANEL_CSS
    assert ".session-current-marker {" in SIMPLE_PANEL_CSS
    assert ".session-meta {" in SIMPLE_PANEL_CSS
    assert ".session-meta .session-artifact-badge {" in SIMPLE_PANEL_CSS
    assert ".session-date-tag {" not in SIMPLE_PANEL_CSS
    assert ".session-metrics {" not in SIMPLE_PANEL_CSS


def test_simple_panel_history_session_items_render_query_first_rows():
    render_session_button = SIMPLE_PANEL_JS.split("function renderSessionButton(session)", 1)[1].split(
        "function renderSessions()", 1
    )[0]

    assert 'btn.className = \'session-item\';' in render_session_button
    assert "session.id === replaySessionId" in render_session_button
    assert 'class="session-main-row"' in render_session_button
    assert 'class="session-primary"' in render_session_button
    assert 'class="session-current-marker"' in render_session_button
    assert 'class="session-meta"' in render_session_button
    assert "sessionMetaHtml(session)" in render_session_button
    assert "startReplay(session.id)" in render_session_button
    assert 'class="session-title-row"' not in SIMPLE_PANEL_JS
    assert 'class="session-date-tag' not in SIMPLE_PANEL_JS
    assert 'class="session-query"' not in SIMPLE_PANEL_JS
    assert 'class="session-metrics"' not in SIMPLE_PANEL_JS
    assert 'trajectory</span>' not in render_session_button
    assert 'class="btn-icon"' not in render_session_button
    assert "M8 5v14l11-7z" not in render_session_button
    assert "▶" not in render_session_button


def test_simple_panel_history_session_meta_labels_count_as_actions():
    # step_count counts executed actions, so the history-drawer label reads "actions".
    session_meta = SIMPLE_PANEL_JS.split("function sessionMetaHtml(session)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "${escHtml(session.step_count || 0)} actions</span>" in session_meta
    assert " steps</span>" not in session_meta


def test_simple_panel_uses_simple_layout_overrides():
    assert "body.simple-ui" in SIMPLE_PANEL_CSS
    assert 'grid-template-areas:\n    "header header        header"\n    "right-aside right-resizer main"\n    "right-aside right-resizer footer";' in SIMPLE_PANEL_CSS
    assert "--right-aside-w: 360px;" in SIMPLE_PANEL_CSS
    assert "body.simple-ui aside#right-sidebar" in SIMPLE_PANEL_CSS
    assert "body.simple-ui #left-sidebar" in SIMPLE_PANEL_CSS
    assert "body.simple-ui [data-view=\"graph\"]" in SIMPLE_PANEL_CSS
    assert "function replayArtifactHref(path, expectedDir = 'history')" in SIMPLE_GRAPH_JS
    assert "function renderActionArtifacts(artifacts)" in SIMPLE_GRAPH_JS
    assert "function recordActionExecution(_event) {}" in SIMPLE_GRAPH_JS


def test_simple_panel_graph_action_count_legend_uses_viridis_palette():
    assert "--graph-work-color-low:      #482878;" in SIMPLE_PANEL_CSS
    assert "--graph-work-color-low-mid:  #3e4989;" in SIMPLE_PANEL_CSS
    assert "--graph-work-color-mid:      #26828e;" in SIMPLE_PANEL_CSS
    assert "--graph-work-color-high-mid: #35b779;" in SIMPLE_PANEL_CSS
    assert "--graph-work-color-high:     #fde725;" in SIMPLE_PANEL_CSS
    assert "background: linear-gradient(90deg, var(--graph-work-color-low) 0%, var(--graph-work-color-low-mid) 25%, var(--graph-work-color-mid) 50%, var(--graph-work-color-high-mid) 75%, var(--graph-work-color-high) 100%);" in SIMPLE_PANEL_CSS


def test_simple_panel_right_panel_shows_only_step_screenshot():
    assert "function renderActionScreenshotCard(label, href)" in SIMPLE_GRAPH_JS
    artifact_renderer = SIMPLE_GRAPH_JS.split("function renderActionArtifacts(artifacts)", 1)[1].split(
        "function renderRightPanelAuxiliarySections", 1
    )[0]

    assert "after_screenshot_path || artifacts.screenshot_path" in artifact_renderer
    assert "before_screenshot_path" in artifact_renderer
    assert "simple-screenshot-link" in SIMPLE_GRAPH_JS
    assert "action_clip_gif_path" not in artifact_renderer
    assert "action_gif_path" not in artifact_renderer
    assert "video_path" not in artifact_renderer
    assert "renderBeforeAfterCompare" not in artifact_renderer

    store_artifacts = SIMPLE_PANEL_JS.split("function storeArtifactsForStep(stepId, artifacts)", 1)[1].split(
        "function upsertActionSummary", 1
    )[0]
    assert "if (selectedTimelineStepId == null)" in store_artifacts
    assert "renderActionStepAdditionalInfo(key);" in store_artifacts
    assert "function renderSimpleActionDetails(calls)" in SIMPLE_PANEL_JS
    assert "renderSimpleActionDetails(calls);" in SIMPLE_PANEL_JS
    assert ".simple-screenshot-link img" in SIMPLE_PANEL_CSS
    assert "body.simple-ui .simple-action-details" in SIMPLE_PANEL_CSS


def test_simple_panel_step_complete_removes_non_action_summary_cards():
    step_complete_case = SIMPLE_PANEL_JS.split("case 'step_complete':", 1)[1].split(
        "case 'task_complete':", 1
    )[0]
    remove_helper = SIMPLE_PANEL_JS.split("function removeNonActionStep(stepId)", 1)[1].split(
        "\nfunction ", 1
    )[0]

    assert "let actionExecutionsByStep = new Map();" in SIMPLE_PANEL_JS
    assert "function removeNonActionStep(stepId)" in SIMPLE_PANEL_JS
    assert "const card = actionSummaryCardsByStep.get(key);" in remove_helper
    assert "if (card) card.remove();" in remove_helper
    assert "actionSummaryCardsByStep.delete(key);" in remove_helper
    assert "actionSummariesByStep.delete(key);" in remove_helper
    assert "timelineStepGroupHasMeaningfulChildren(group)" in remove_helper
    assert "!child.classList.contains('action-summary-card')" in SIMPLE_PANEL_JS
    assert "storeActionExecutionForStats(ev);" in SIMPLE_PANEL_JS
    assert "const actions = actionExecutionsByStep.get(key);" in step_complete_case
    assert "if (!actions || !actions.length) removeNonActionStep(ev.step_id);" in step_complete_case


def test_simple_panel_running_state_locks_input_without_dimming_stop_button():
    set_input = SIMPLE_PANEL_JS.split("function setInputEnabled(enabled) {", 1)[1].split(
        "function resetTimeline", 1
    )[0]

    assert ".input-shell.input-locked" in SIMPLE_PANEL_CSS
    assert ".input-shell.composer-disabled" in SIMPLE_PANEL_CSS
    assert ".input-shell.disabled" not in SIMPLE_PANEL_CSS
    assert "const inputLocked = !enabled && (isRunning || isSubmitting) && !replayMode;" in set_input
    assert "const composerDisabled = !enabled && !inputLocked;" in set_input
    assert "inputShell.classList.toggle('input-locked', inputLocked);" in set_input
    assert "inputShell.classList.toggle('composer-disabled', composerDisabled);" in set_input
    assert "inputShell.classList.toggle('disabled'" not in set_input


def test_simple_panel_static_assets_are_served():
    client = TestClient(app)
    for path, expected in (
        ("/static/panel.css", "text/css"),
        ("/static/graph.js", "javascript"),
        *[(f"/static/panel/{name}", "javascript") for name in _SIMPLE_PANEL_JS_PARTS],
        ("/static/panel.js", "javascript"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-store"

    html = client.get("/")
    assert html.status_code == 200
    assert html.headers["cache-control"] == "no-store"
    assert "/static/panel.css" in html.text
    assert "/static/graph.js" in html.text
    for name in _SIMPLE_PANEL_JS_PARTS:
        assert f"/static/panel/{name}" in html.text
    assert "/static/panel.js" in html.text


def test_simple_panel_served_html_cache_busts_local_static_assets():
    html = TestClient(app).get("/")

    assert html.status_code == 200
    for asset in ("panel.css", "graph.js", *[f"panel/{name}" for name in _SIMPLE_PANEL_JS_PARTS], "panel.js"):
        assert re.search(rf"/static/{re.escape(asset)}\?v=\d+", html.text)


def test_simple_task_endpoint_uses_shared_bridge_queue():
    reset_task_state_for_tests()
    client = TestClient(app)
    with patch("ui.c1_simple_ui.server.task_queue") as mock_queue:
        response = client.post("/task", json={"query": "use simple ui"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_queue.put.assert_called_once_with("use simple ui")
    reset_task_state_for_tests()
