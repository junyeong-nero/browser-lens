import re
from pathlib import Path

from fastapi.testclient import TestClient

from ui.c3_browser_lens.server import app
from ui.server_core import create_panel_app


PANEL_HTML_ONLY = Path("src/ui/c3_browser_lens/panel.html").read_text(encoding="utf-8")


def _read_css_bundle(entrypoint: str) -> str:
    path = Path(entrypoint)
    text = path.read_text(encoding="utf-8")
    imports = re.findall(r'@import url\("([^"]+)"\);', text)
    if not imports:
        return text
    return "\n".join((path.parent / imported).read_text(encoding="utf-8") for imported in imports)


PANEL_CSS = _read_css_bundle("src/ui/c3_browser_lens/static/panel.css")
_SHARED_PANEL_JS_PARTS = (
    "panel-state.js",
    "panel-timeline.js",
    "panel-sidebar.js",
    "panel-stats-data.js",
    "panel-stats-render.js",
    "panel-events.js",
    "panel-markdown.js",
    "panel-replay.js",
    "panel-input.js",
)
PANEL_JS = "\n".join(
    Path(f"src/ui/shared/static/panel/{name}").read_text(encoding="utf-8")
    for name in _SHARED_PANEL_JS_PARTS
)
_GRAPH_JS_PARTS = (
    "graph-state.js",
    "graph-artifacts.js",
    "graph-noop-evidence.js",
    "graph-right-panel.js",
    "graph-cues.js",
    "graph-build.js",
    "graph-selection.js",
    "graph-layout.js",
    "graph-tooltip.js",
    "graph-render.js",
)
GRAPH_JS = "\n".join(
    Path(f"src/ui/c3_browser_lens/static/graph/{name}").read_text(encoding="utf-8")
    for name in _GRAPH_JS_PARTS
)
# Existing static-contract tests search the asset that now owns the code/CSS.
PANEL_HTML = PANEL_HTML_ONLY + "\n" + PANEL_CSS + "\n" + PANEL_JS + "\n" + GRAPH_JS




def test_panel_loads_split_static_assets():
    assert "<title>BrowserLens</title>" in PANEL_HTML_ONLY
    assert '<span class="title" id="hdr-title">BrowserLens</span>' in PANEL_HTML_ONLY
    assert '<link rel="stylesheet" href="/static/panel.css">' in PANEL_HTML_ONLY
    assert '<script src="https://d3js.org/d3.v7.min.js"></script>' in PANEL_HTML_ONLY
    for name in _GRAPH_JS_PARTS:
        assert f'<script src="/static/graph/{name}"></script>' in PANEL_HTML_ONLY
    for name in _SHARED_PANEL_JS_PARTS:
        assert f'<script src="/shared-static/panel/{name}"></script>' in PANEL_HTML_ONLY
    assert '<script src="/static/panel.js"></script>' not in PANEL_HTML_ONLY
    assert '<style>' not in PANEL_HTML_ONLY
    assert '<script>' not in PANEL_HTML_ONLY


def test_panel_static_assets_are_served():
    client = TestClient(app)
    paths = [
        ('/static/panel.css', 'text/css'),
    ] + [(f'/static/graph/{name}', 'javascript') for name in _GRAPH_JS_PARTS]
    paths += [(f'/shared-static/panel/{name}', 'javascript') for name in _SHARED_PANEL_JS_PARTS]
    for path, expected in paths:
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.headers['content-type']
        assert response.headers['cache-control'] == 'no-store'

    html = client.get('/')
    assert html.status_code == 200
    assert html.headers['cache-control'] == 'no-store'
    assert '/static/panel.css' in html.text
    for name in _GRAPH_JS_PARTS:
        assert f'/static/graph/{name}' in html.text
    for name in _SHARED_PANEL_JS_PARTS:
        assert f'/shared-static/panel/{name}' in html.text
    assert '/static/panel.js' not in html.text


def test_panel_served_html_cache_busts_local_static_assets():
    html = TestClient(app).get('/')

    assert html.status_code == 200
    assets = ['panel.css'] + [f'graph/{name}' for name in _GRAPH_JS_PARTS]
    for asset in assets:
        assert re.search(rf'/static/{re.escape(asset)}\?v=\d+', html.text)
    for asset in [f'panel/{name}' for name in _SHARED_PANEL_JS_PARTS]:
        assert re.search(rf'/shared-static/{re.escape(asset)}\?v=\d+', html.text)


def test_panel_history_drawer_markup_and_state_refs_are_available():
    load_sessions = PANEL_JS.split("async function loadSessions()", 1)[1].split(
        "function showReplayMessage", 1
    )[0]

    assert 'id="sessions-panel" class="hidden sessions-drawer" role="dialog" aria-label="History"' in PANEL_HTML
    assert 'aria-modal="false"' in PANEL_HTML
    assert 'class="sessions-head-main"' in PANEL_HTML
    assert 'class="sessions-title"' in PANEL_HTML
    assert 'id="sessions-summary"' in PANEL_HTML
    assert 'id="sessions-search"' in PANEL_HTML
    assert 'class="sessions-message"' in PANEL_JS
    assert 'Loading saved sessions' in load_sessions
    assert 'loading…' not in load_sessions
    assert 'aria-label="Search history"' in PANEL_HTML
    assert 'placeholder="Search query, session id, or model"' in PANEL_HTML
    assert 'class="sessions-body"' in PANEL_HTML
    assert 'id="sessions-list"' in PANEL_HTML
    assert 'Loading saved sessions' in PANEL_HTML
    assert "const sessionsSearch = document.getElementById('sessions-search');" in PANEL_HTML
    assert "const sessionsSummary = document.getElementById('sessions-summary');" in PANEL_HTML
    assert 'aria-label="Close History"' in PANEL_HTML
    assert 'title="Close History"' in PANEL_HTML


def test_panel_history_drawer_filters_groups_and_renders_query_first_rows():
    load_sessions = PANEL_JS.split("async function loadSessions()", 1)[1].split(
        "function showReplayMessage", 1
    )[0]

    assert "let savedSessions = [];" in PANEL_JS
    assert "let sessionsSearchQuery = '';" in PANEL_JS
    assert "function sessionMatchesSearch(session, query)" in PANEL_JS
    assert "function compareSessionsByLogNameDesc(left, right)" in PANEL_JS
    assert "function groupSessionsByDate(sessions)" in PANEL_JS
    assert "function renderSessions()" in PANEL_JS
    assert "function updateSessionsSummary(total, visible)" in PANEL_JS
    assert "session.query || 'unknown task'" in PANEL_JS
    assert "[session.query, session.id, session.model]" in PANEL_JS
    assert "sessionsSearch.addEventListener('input'" in PANEL_JS
    assert "savedSessions = Array.isArray(data.sessions) ? data.sessions : [];" in load_sessions
    assert "renderSessions();" in load_sessions
    assert ".sort(compareSessionsByLogNameDesc)" in PANEL_JS
    assert 'class="session-primary"' in PANEL_JS
    assert 'class="session-meta"' in PANEL_JS
    assert 'class="session-current-marker"' in PANEL_JS
    assert 'class="session-date-group"' in PANEL_JS
    assert 'class="session-artifact-badge">events</span>' in PANEL_JS
    assert 'class="session-artifact-badge">video</span>' in PANEL_JS
    assert 'class="sessions-message"' in PANEL_JS
    assert 'No sessions match your search' in PANEL_JS
    assert 'class="session-date-tag' not in PANEL_JS
    assert 'class="session-metrics"' not in PANEL_JS


def test_panel_served_html_reflects_file_changes_without_restart(tmp_path):
    ui_dir = tmp_path / "ui"
    static_dir = ui_dir / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "panel.js").write_text("console.log('panel');\n", encoding="utf-8")
    panel_path = ui_dir / "panel.html"
    panel_path.write_text('<script src="/static/panel.js"></script><div id="old-panel"></div>', encoding="utf-8")

    test_app = create_panel_app(
        ui_dir=ui_dir,
        static_asset_names=("panel.js",),
        task_queue_getter=lambda: None,
    )
    client = TestClient(test_app)

    first = client.get("/")
    assert first.status_code == 200
    assert 'id="old-panel"' in first.text

    panel_path.write_text('<script src="/static/panel.js"></script><div id="new-panel"></div>', encoding="utf-8")
    second = client.get("/")

    assert second.status_code == 200
    assert 'id="new-panel"' in second.text
    assert 'id="old-panel"' not in second.text
    assert re.search(r'/static/panel\.js\?v=\d+', second.text)


def test_panel_model_placeholder_is_not_hardcoded_to_gemini():
    assert '<span id="agent-model">gemini</span>' not in PANEL_HTML
    assert '<span id="agent-model">—</span>' in PANEL_HTML
    assert 'placeholder="Describe what you want the agent to do…"' in PANEL_HTML
    input_agent_html = PANEL_HTML_ONLY.split('<div class="input-agent">', 1)[1].split("</div>", 1)[0]
    assert "browser-agent" not in input_agent_html
    assert "agent-name" not in input_agent_html
    input_controls_css = PANEL_HTML.split(".input-controls {", 1)[1].split("}", 1)[0]
    input_agent_css = PANEL_HTML.split(".input-agent {", 1)[1].split("}", 1)[0]
    textarea_css = PANEL_HTML.split("textarea {", 1)[1].split("}", 1)[0]
    assert "justify-content: flex-end;" in input_controls_css
    assert "margin-left: auto;" in input_agent_css
    assert "width: 100%;" in textarea_css


def test_panel_input_composer_uses_compact_height():
    input_shell_css = PANEL_HTML.split(".input-shell {", 1)[1].split("}", 1)[0]
    input_controls_css = PANEL_HTML.split(".input-controls {", 1)[1].split("}", 1)[0]
    textarea_css = PANEL_HTML.split("textarea {", 1)[1].split("}", 1)[0]

    assert "padding: 10px 14px 10px;" in input_shell_css
    assert "margin-top: 8px;" in input_controls_css
    assert "min-height: 32px;" in input_controls_css
    assert "min-height: 24px;" in textarea_css
    assert "max-height: 148px;" in textarea_css


def test_panel_updates_model_name_from_session_ready_event():
    session_ready_case = PANEL_HTML.split("case 'session_ready':", 1)[1].split(
        "case 'task_started':", 1
    )[0]

    assert "const agentModel  = document.getElementById('agent-model');" in PANEL_HTML
    assert "function setAgentModel(modelName)" in PANEL_HTML
    assert "setAgentModel(ev.model_name);" in PANEL_HTML
    assert "addRow('dim', 'agent ready.');" not in session_ready_case


def test_panel_replan_preserves_existing_subgoals_before_failed_one():
    assert "let pendingReplanFailedSubgoalId = null;" in PANEL_HTML
    assert "function replaceSubgoalsAfterFailed(failedId, revisedList)" in PANEL_HTML
    assert "subgoals = subgoals.slice(0, failedIdx + 1).concat(revisedSubgoals);" in PANEL_HTML


def test_panel_replanned_event_replaces_only_after_failed_subgoal():
    replanned_case = PANEL_HTML.split("case 'planner_replanned':", 1)[1].split(
        "case 'subgoal_started':", 1
    )[0]
    assert "replaceSubgoalsAfterFailed(" in replanned_case
    assert "ev.failed_subgoal_id != null ? ev.failed_subgoal_id : pendingReplanFailedSubgoalId" in replanned_case
    assert "setSubgoals(items);" not in replanned_case


def test_panel_graph_tab_shows_only_trajectory_graph():
    assert 'data-graph-mode="state"' not in PANEL_HTML
    assert "Browser State" not in PANEL_HTML
    assert "function buildStateGraphData()" not in PANEL_HTML
    assert "function setupGraphModeToggle()" not in PANEL_HTML
    assert "function selectedGraphData()" in PANEL_HTML
    assert "return buildTrajectoryGraphData();" in PANEL_HTML


def test_panel_stats_tab_renders_tool_statistics_view():
    assert 'class="view-tab icon-label" data-view="stats"' in PANEL_HTML_ONLY
    assert "<span>Stats</span>" in PANEL_HTML_ONLY
    assert '<div class="view-pane" data-view="stats" id="stats-wrap">' in PANEL_HTML_ONLY
    for element_id in (
        "stats-help-btn",
        "stats-help-panel",
        "stats-empty",
        "stats-overview",
        "stats-tool-chart",
        "stats-behavior-chart",
        "stats-diagnostics",
    ):
        assert f'id="{element_id}"' in PANEL_HTML_ONLY

    for selector in (
        "#stats-wrap",
        ".stats-grid",
        ".stat-card",
        ".stats-chart-row",
        ".stats-chart",
        ".stats-donut-segment",
        ".stats-chart-tooltip",
        ".stats-diagnostics-list",
        ".stats-help-btn",
        ".stats-help-panel",
    ):
        assert selector in PANEL_CSS


def test_panel_stats_help_explains_metrics_and_tool_categories():
    assert 'id="stats-help-btn"' in PANEL_HTML_ONLY
    assert 'aria-controls="stats-help-panel"' in PANEL_HTML_ONLY
    assert 'viewBox="0 -960 960 960"' in PANEL_HTML_ONLY
    assert "M513.5-254.5Q528-269" in PANEL_HTML_ONLY
    assert 'id="stats-help-panel"' in PANEL_HTML_ONLY
    assert 'role="dialog"' in PANEL_HTML_ONLY

    for label in (
        "Tool calls",
        "Tool Usage",
        "Behavior Mix",
        "Observation-to-action",
        "Observation",
        "Interaction",
        "Navigation",
        "Recovery",
        "Waiting",
    ):
        assert label in PANEL_HTML_ONLY

    assert "const statsHelpBtn = document.getElementById('stats-help-btn');" in PANEL_JS
    assert "function openStatsHelp()" in PANEL_JS
    assert "function closeStatsHelp()" in PANEL_JS
    assert "statsHelpBtn.addEventListener('click', openStatsHelp);" in PANEL_JS
    assert "statsHelpPanel.hidden = false;" in PANEL_JS
    assert "statsHelpPanel.hidden = true;" in PANEL_JS
    assert ".stats-help-panel[hidden]" in PANEL_CSS


def test_panel_stats_aggregates_tool_calls_and_diagnostics():
    assert "const OBSERVATION_TOOLS = new Set([" in PANEL_JS
    assert "const RECOVERY_TOOLS = new Set([" in PANEL_JS
    assert "const WAIT_TOOLS = new Set([" in PANEL_JS
    assert "let actionExecutionsByStep = new Map();" in PANEL_JS
    assert "function buildStatsSnapshot()" in PANEL_JS
    assert "function collectStatsExecutions()" in PANEL_JS
    assert "function summarizeToolOutcomes(calls, executions)" in PANEL_JS
    assert "function isStatsExecutionError(execution)" in PANEL_JS
    assert "function actionSignatureForStats(name, args)" in PANEL_JS
    assert "function renderStatsCircularChart(container, rows, total, caption = 'calls', colorway = 'tool')" in PANEL_JS
    assert "function attachStatsChartHover(container)" in PANEL_JS
    assert "function renderStats()" in PANEL_JS
    assert "computeStatsCueCounts()" in PANEL_JS
    assert "recordStepError(ev.step_id, ev.error_message);" in PANEL_JS
    assert "storeActionExecutionForStats(ev);" in PANEL_JS
    assert "updateStats();" in PANEL_JS
    assert "Tool success" in PANEL_JS
    assert "stats-donut-segment" in PANEL_JS
    assert "data-stats-tooltip" in PANEL_JS
    assert "Skipped calls" in PANEL_JS
    assert "Ineffective executions" in PANEL_JS
    assert "Repeated actions" in PANEL_JS
    assert "Observation-to-action" in PANEL_JS
    assert "Navigation churn" in PANEL_JS


def test_panel_stats_uses_separate_chart_colorways():
    assert "const STATS_TOOL_COLORWAY = [" in PANEL_JS
    assert "const STATS_BEHAVIOR_COLORWAY = {" in PANEL_JS
    assert "var(--tds-fill-brand)" in PANEL_JS
    assert "var(--tds-fill-success)" in PANEL_JS
    assert "var(--tds-fill-warning)" in PANEL_JS
    assert "var(--tds-fill-danger)" in PANEL_JS
    assert "function statsFallbackColor(index, hueOffset = 0)" in PANEL_JS
    assert "function statsChartColor(row, index, colorway = 'tool')" in PANEL_JS


def test_panel_llm_inference_uses_trace_artifact_reference_when_available():
    assert "tracePath: ev.llm_trace_path || null" in PANEL_JS
    assert "rawContextOmitted: !!ev.raw_context_omitted" in PANEL_JS
    assert "rawResponseOmitted: !!ev.raw_response_omitted" in PANEL_JS
    assert "replayArtifactHref(inference.tracePath, 'history')" in GRAPH_JS
    assert "LLM trace artifact" in GRAPH_JS
    assert "function loadLlmTracePreviews(container)" in GRAPH_JS
    assert "data-llm-trace-src" in GRAPH_JS
    assert "data-llm-trace-field" in GRAPH_JS
    assert "payload ? payload[field] : null" in GRAPH_JS
    assert "hydrateLlmTraceLoaders(section);" in GRAPH_JS


def test_panel_graph_does_not_retain_raw_aria_text_on_action_nodes():
    assert "preAriaText" not in GRAPH_JS
    assert "postAriaText" not in GRAPH_JS
    assert "preAriaSig" in GRAPH_JS
    assert "postAriaSig" in GRAPH_JS
    assert "oklch(" not in PANEL_JS
    assert "renderStatsCircularChart(statsToolChart, snapshot.toolRows, snapshot.totalToolCalls, 'tool calls', 'tool')" in PANEL_JS
    assert "renderStatsCircularChart(statsBehaviorChart, snapshot.behaviorRows, snapshot.totalToolCalls, 'behavior', 'behavior')" in PANEL_JS


def test_panel_stats_signature_ignores_resolved_ref_name_metadata():
    stats_signature_helpers = PANEL_JS.split("function stableStatsValue(value)", 1)[1].split(
        "function toolBehaviorCategory", 1
    )[0]

    assert "const STATS_SIGNATURE_IGNORED_ARG_KEYS = new Set([" in PANEL_JS
    assert "'ref_name'," in PANEL_JS
    assert "if (STATS_SIGNATURE_IGNORED_ARG_KEYS.has(key)) return acc;" in stats_signature_helpers


def test_panel_stats_view_refreshes_on_tab_activation_and_reset():
    set_view = PANEL_JS.split("function setMainView(view)", 1)[1].split(
        "function activateMainView", 1
    )[0]
    activate_view = PANEL_JS.split("function activateMainView(view, options = {})", 1)[1].split(
        "(function setupTabs", 1
    )[0]
    reset_body = PANEL_JS.split("function resetSidebar()", 1)[1].split(
        "function storeLlmInference", 1
    )[0]

    assert "document.body.classList.toggle('view-stats', view === 'stats');" in set_view
    assert "if (view === 'stats') {" in activate_view
    assert "updateStats({ force: true });" in activate_view
    assert "resetStats();" in reset_body


def test_panel_replay_uses_recorded_events_without_backend_trajectory_fetch():
    start_replay = PANEL_JS.split("async function startReplay(sessionId)", 1)[1].split(
        "sessionsBtn.addEventListener", 1
    )[0]

    assert "fetchReplayBackendTrajectoryGraph(sessionId)" not in start_replay
    assert "/graph" not in PANEL_JS
    assert "/cues" not in PANEL_JS
    assert "case 'trajectory_graph_updated':" not in PANEL_JS


def test_graph_state_tracks_only_client_side_payload():
    assert "let backendTrajectoryGraph = null;" not in GRAPH_JS
    assert "let backendTrajectoryCues = null;" not in GRAPH_JS
    assert "function setBackendTrajectoryGraph(payload, cuesPayload = null)" not in GRAPH_JS
    assert "function clearBackendTrajectoryGraph()" not in GRAPH_JS
    reset_body = GRAPH_JS.split("function resetTrajectoryGraphState(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "clearBackendTrajectoryGraph();" not in reset_body


def test_graph_builder_uses_client_side_trajectory_graph():
    assert "function buildBackendGraphData(payload, graphMode, drilldown)" not in GRAPH_JS
    assert "backendTrajectoryGraph" not in GRAPH_JS
    selected = GRAPH_JS.split("function selectedGraphData()", 1)[1].split(
        "\nfunction ", 1
    )[0]

    assert "return buildTrajectoryGraphData();" in selected
    assert "function buildUrlGraphData()" in GRAPH_JS
    assert "function buildViewportGraphData(urlId)" in GRAPH_JS
    assert "function buildActionGraphData(viewportId)" in GRAPH_JS


def test_panel_graph_has_view_controls_and_vertical_bottom_right_legend():
    assert 'id="graph-controls" class="graph-controls"' in PANEL_HTML
    assert 'id="graph-fit" class="icon-only" type="button" aria-label="Show all graph nodes"' in PANEL_HTML
    assert 'id="graph-zoom-in" class="icon-only" type="button" aria-label="Zoom graph in"' in PANEL_HTML
    assert 'id="graph-zoom-out" class="icon-only" type="button" aria-label="Zoom graph out"' in PANEL_HTML
    assert "function fitToNodes()" in PANEL_HTML
    assert "function zoomBy(factor)" in PANEL_HTML
    assert "zoomBehavior.scaleBy" in PANEL_HTML
    assert "zoomBehavior.transform" in PANEL_HTML

    assert '<div class="legend-title">visit count</div>' in PANEL_HTML


def test_panel_uses_action_artifacts_for_hierarchical_graph():
    action_case = PANEL_HTML.split("case 'action_executed':", 1)[1].split(
        "case 'step_error':", 1
    )[0]
    assert "recordBrowserStateGraph(ev.artifacts);" not in action_case
    assert "recordActionExecution(ev);" in action_case
    assert "function viewportInfoFromArtifacts(artifacts)" in PANEL_HTML
    assert "function scrollBucketKey(scroll, bucketSize = 20)" not in PANEL_HTML
    assert "key: scrollBucketKey(scroll)" not in PANEL_HTML
    assert "key: `${size}|${scroll}`" in PANEL_HTML
    assert "stateGraphLeaf(artifacts, 'viewport.size')" in PANEL_HTML
    assert "stateGraphLeaf(artifacts, 'viewport.scroll')" in PANEL_HTML


def test_panel_url_identity_canonicalizes_query_params():
    url_parser = GRAPH_JS.split("function parseUrlParts(url)", 1)[0]
    parse_url_parts = GRAPH_JS.split("function parseUrlParts(url)", 1)[1].split(
        "\nfunction ", 1
    )[0]

    assert "const URL_TRACKING_PARAMS = new Set([" in url_parser
    assert "'utm_source'" in url_parser
    assert "'gclid'" in url_parser
    assert "'fbclid'" in url_parser
    assert "function canonicalSearch(search)" in url_parser
    assert "new URLSearchParams(search || '')" in url_parser
    assert "URL_TRACKING_PARAMS.has(name.toLowerCase())" in url_parser
    assert "params.delete(name);" in url_parser
    assert "params.sort();" in url_parser
    assert "return out ? `?${out}` : '';" in url_parser
    assert "const key = u.origin + u.pathname + canonicalSearch(u.search);" in parse_url_parts
    assert "return { key, host, path, full: url };" in parse_url_parts
    assert "const path = (u.pathname || '/') + (u.search || '');" in parse_url_parts


def test_panel_graph_supports_url_viewport_action_drilldown():
    assert "URL → viewport → action" in PANEL_HTML
    assert "Each level preserves chronological DAG edges" in PANEL_HTML
    assert "let graphDrilldown = { level: 'url', urlId: null, viewportId: null };" in PANEL_HTML
    assert "function buildUrlGraphData()" in PANEL_HTML
    assert "function buildViewportGraphData(urlId)" in PANEL_HTML
    assert "function buildActionGraphData(viewportId)" in PANEL_HTML
    assert "function buildSequentialLinks(sequence, allowedIds, rootId = null, allowSelfLoops = false)" in PANEL_HTML
    assert "function drillGraphNode(d)" in PANEL_HTML
    assert "setGraphDrilldown({ level: 'viewport', urlId: crumb.urlId, viewportId: null });" in PANEL_HTML
    assert 'id="graph-breadcrumb"' in PANEL_HTML


def test_panel_viewport_and_action_drilldowns_use_step_dag_edges():
    assert "viewportSequence: []" in PANEL_HTML
    assert "actionSequence: []" in PANEL_HTML
    assert "urlNode.viewportSequence.push(viewportId);" in PANEL_HTML
    # Actions are anchored to the pre-action viewport, not the post-action viewport.
    assert "anchorViewportNode.actionSequence.push(actionId);" in PANEL_HTML

    viewport_builder = PANEL_HTML.split("function buildViewportGraphData(urlId)", 1)[1].split(
        "function buildActionGraphData(viewportId)", 1
    )[0]
    assert "buildSequentialLinks(urlNode.viewportSequence, viewportIds, null)" in viewport_builder
    assert "viewports.map(vp => ({ source: root.id, target: vp.id" not in viewport_builder
    assert "nodes: viewports," in viewport_builder

    action_builder = PANEL_HTML.split("function buildActionGraphData(viewportId)", 1)[1].split(
        "function trajectoryLabelFor(n)", 1
    )[0]
    assert "buildSequentialLinks(viewportNode.actionSequence, actionIds, null, true)" in action_builder
    assert "actions.map(action => ({ source: root.id, target: action.id" not in action_builder
    assert "nodes: actions," in action_builder


def test_panel_sequence_links_anchor_first_node_and_preserve_returns():
    link_builder = PANEL_HTML.split("function buildSequentialLinks(sequence, allowedIds, rootId = null, allowSelfLoops = false)", 1)[1].split(
        "function buildTrajectoryGraphData()", 1
    )[0]
    assert "let previous = rootId;" in link_builder
    assert "if (previous && (allowSelfLoops || previous !== id))" in link_builder
    assert "const edgeKey = `${previous}|${id}`;" in link_builder
    assert "if (edge) edge.count += 1;" in link_builder


def test_panel_uses_user_friendly_viewport_and_action_labels():
    assert "function scrollLabel(scroll)" in PANEL_HTML
    assert "function viewportLabel(viewport, stepId)" in PANEL_HTML
    assert "function actionLabel(actionName, args)" in PANEL_HTML
    assert "const stepLabel = stepId != null ? `Screen #${stepId}` : 'Screen view';" in PANEL_HTML
    assert "return `${stepLabel} · ${scrollLabel(viewport.scroll)}`;" in PANEL_HTML
    assert "label: viewportLabel(viewport, ev.step_id)" in PANEL_HTML
    assert "label: actionLabel(actionName, actionArgs)" in PANEL_HTML
    assert "if (actionName === 'click_at') return `Click at (${values.x}, ${values.y})`;" in PANEL_HTML
    assert "if (actionName === 'navigate') return `Open ${truncateLabel(values.url || 'page', 40)}`;" in PANEL_HTML
    assert "return String(actionName || 'Action').replace(/_/g, ' ');" in PANEL_HTML


def test_panel_graph_truncates_rendered_node_labels_without_changing_data_labels():
    assert "const GRAPH_NODE_LABEL_MAX_CHARS = 28;" in PANEL_HTML
    assert "function compactGraphNodeLabel(label, maxChars = GRAPH_NODE_LABEL_MAX_CHARS)" in PANEL_HTML
    assert "function displayGraphNodeLabel(d)" in PANEL_HTML
    assert "return text.length <= maxChars ? text : text.slice(0, maxChars - 1) + '…';" in PANEL_HTML
    assert "nodeSel.select('text.graph-node-label').text(displayGraphNodeLabel);" in PANEL_HTML

    graph_renderer = PANEL_HTML.split("function update(payload)", 1)[1].split(
        "function reset()", 1
    )[0]
    assert "nodeSel.select('text').text(d => d.label || d.id);" not in graph_renderer
    assert "label: actionLabel(actionName, actionArgs)" in PANEL_HTML
    assert "const title = d.label || d.host || d.actionName || d.id;" in PANEL_HTML


def test_panel_action_graph_reuses_same_action_nodes_and_draws_cycles():
    assert "function stableActionValue(value)" in PANEL_HTML
    assert "function actionSignature(actionName, args)" in PANEL_HTML
    assert "let actionNodeIdByStep = new Map();" in PANEL_HTML
    # Actions are anchored to the pre-action viewport, not the post-action viewport.
    assert "const actionId = `action|${anchorViewportId}|${actionSignature(actionName, actionArgs)}`;" in PANEL_HTML
    assert "let actionNode = trajectoryActions.get(actionId);" in PANEL_HTML
    assert "if (!actionNode)" in PANEL_HTML
    assert "stepIds: []," in PANEL_HTML
    assert "actionNode.stepIds.push(stepIdKey);" in PANEL_HTML
    assert "actionNodeIdByStep.set(stepIdKey, actionId);" in PANEL_HTML
    assert "actionNode.visits += 1;" in PANEL_HTML
    assert "actionNode.step = ev.step_id;" in PANEL_HTML
    assert "anchorViewportNode.actionSequence.push(actionId);" in PANEL_HTML
    assert "buildSequentialLinks(viewportNode.actionSequence, actionIds, null, true)" in PANEL_HTML
    assert "linkG.selectAll('path.graph-link')" in PANEL_HTML
    assert "function graphLinkPath(d, radiusForNode)" in PANEL_HTML
    assert "return `M ${sx} ${sy - 8} C" in PANEL_HTML
    assert "function detectCycleEdges(links)" in PANEL_HTML
    assert "const isCycleEdge = !!source && !!target && (source === target || (cyclicNodes.has(source) && cyclicNodes.has(target)));" in PANEL_HTML
    assert "detectCycleEdges(buildSequentialLinks(viewportNode.actionSequence, actionIds, null, true))" in PANEL_HTML
    assert ".classed('cycle', d => !!d.isCycleEdge)" in PANEL_HTML
    assert ".graph-link.cycle" in PANEL_HTML
    assert 'id="graph-arrow-cycle"' in PANEL_HTML


def test_panel_graph_action_artifacts_prioritize_replay_and_inline_compare():
    assert "function renderActionReplayVideoCard(label, href)" in PANEL_HTML
    assert "function renderActionReplayCard(label, href)" in PANEL_HTML
    assert "function renderBeforeAfterCompare(beforeHref, afterHref)" in PANEL_HTML
    assert "class=\"artifact-primary\"" in PANEL_HTML
    # P5: side-by-side .artifact-split was replaced with a CSS clip-path slider
    # overlay so reviewers can scrub between before/after in one viewport.
    assert "class=\"artifact-slider\"" in PANEL_HTML
    assert "class=\"artifact-slider-after\"" in PANEL_HTML
    assert "class=\"artifact-slider-range\"" in PANEL_HTML
    assert "class=\"artifact-split\"" not in PANEL_HTML
    assert "class=\"artifact-compare-tabs\"" not in PANEL_HTML
    assert "data-compare-mode=\"before\"" not in PANEL_HTML
    assert "data-compare-mode=\"after\"" not in PANEL_HTML
    assert "data-compare-mode=\"split\"" not in PANEL_HTML
    assert "Technical paths" in PANEL_HTML

def test_panel_graph_selection_can_show_llm_raw_context_and_response():
    assert "let llmInferencesByStep = new Map();" in PANEL_HTML
    assert "case 'llm_inference':" in PANEL_HTML
    assert "storeLlmInference(ev);" in PANEL_HTML
    assert "window.getLlmInferenceForStep = getLlmInferenceForStep;" in PANEL_HTML
    assert 'id="side-llm-context-section" class="side-section side-scroll-section side-llm-raw-section" hidden' in PANEL_HTML_ONLY
    assert '<summary data-icon="psychology">View LLM raw context</summary>' in PANEL_HTML_ONLY
    assert 'id="side-llm-response-section" class="side-section side-scroll-section side-llm-raw-section" hidden' in PANEL_HTML_ONLY
    assert '<summary data-icon="terminal">View LLM response</summary>' in PANEL_HTML_ONLY
    assert "function renderLlmContextBody(inference)" in PANEL_HTML
    assert "function renderLlmResponseBody(inference)" in PANEL_HTML
    # P5: signature gained an optional actionNode for ARIA pre/post diff.
    assert "function renderRightPanelAuxiliarySections(inference, artifacts, actionNode)" in PANEL_HTML
    assert "View LLM raw context" in PANEL_HTML
    assert "View LLM response" in PANEL_HTML
    assert "LLM raw context" in PANEL_HTML
    assert "LLM response" in PANEL_HTML
    assert "llmInference: llmInferenceForStep(ev.step_id)" in PANEL_HTML
    assert "renderRightPanelAuxiliarySections(d.llmInference, d.artifacts)" in PANEL_HTML
    assert "setOptionalSideSection(llmContextSection, llmContextBody, llmContextContent);" in PANEL_HTML
    assert "setOptionalSideSection(llmResponseSection, llmResponseBody, llmResponseContent);" in PANEL_HTML
    assert "hydrateCodeBoxCopyButtons(section);" in PANEL_HTML
    assert "function copyTextToClipboard(text)" in PANEL_HTML
    assert "data-copy-codebox" in PANEL_HTML
    assert "navigator.clipboard.writeText(text)" in PANEL_HTML
    assert "Loading raw context from LLM trace..." in PANEL_HTML
    assert "Loading raw response from LLM trace..." in PANEL_HTML
    assert "details.side-section[hidden]" in PANEL_HTML
    assert "display: none;" in PANEL_HTML.split("details.side-section[hidden] {", 1)[1].split("}", 1)[0]


def test_panel_selection_can_show_dom_and_aria_state_artifacts():
    step_render = PANEL_HTML.split("function renderActionStepAdditionalInfo(stepId)", 1)[1].split(
        "function actionGroupStepIds", 1
    )[0]
    group_render = PANEL_HTML.split("function renderActionGroupAdditionalInfo(actionNode)", 1)[1].split(
        "window.renderActionStepAdditionalInfo", 1
    )[0]
    graph_node_selection = PANEL_HTML.split("function renderGraphNodeSelection(d)", 1)[1].split(
        "function renderSelection(d)", 1
    )[0]

    assert 'id="side-dom-state-section" class="side-section side-scroll-section side-browser-state-section browser-state-details" hidden' in PANEL_HTML_ONLY
    assert '<summary data-icon="code_blocks">View DOM State</summary>' in PANEL_HTML_ONLY
    assert 'id="side-aria-state-section" class="side-section side-scroll-section side-browser-state-section browser-state-details" hidden' in PANEL_HTML_ONLY
    assert '<summary data-icon="account_tree">View ARIA State</summary>' in PANEL_HTML_ONLY
    assert "function renderDomStateBody(artifacts, actionNode)" in PANEL_HTML
    assert "function renderAriaStateBody(artifacts, actionNode)" in PANEL_HTML
    assert "function renderBrowserStateMetaLink(label, href, linkText)" in PANEL_HTML
    assert "View DOM State" in PANEL_HTML
    assert "View ARIA State" in PANEL_HTML
    assert "DOM snapshot" in PANEL_HTML
    assert "ARIA snapshot" in PANEL_HTML
    assert "artifacts.html_path || artifacts.after_html_path" in PANEL_HTML
    assert "artifacts.a11y_path || artifacts.after_a11y_path" in PANEL_HTML
    assert "function renderCodeBox(title, text, options = {})" in PANEL_HTML
    assert "class=\"codebox\"" in PANEL_HTML
    assert "class=\"codebox-pre" in PANEL_HTML
    assert "function hydrateBrowserStateButtons(root = document)" in PANEL_HTML
    assert "fetch(src, { cache: 'no-store' })" in PANEL_HTML
    # Step/group selectors thread the action node through so ARIA diff can fire.
    assert "renderRightPanelAuxiliarySections(inference, artifacts, actionNode)" in step_render
    assert "renderRightPanelAuxiliarySections(inference, artifacts, actionNode)" in group_render
    assert "renderRightPanelAuxiliarySections(d.llmInference, d.artifacts)" in graph_node_selection
    assert "hydrateBrowserStateButtons(section);" in PANEL_HTML
    assert "if (section.open) loadBrowserStatePreviews(section);" in PANEL_HTML


def test_panel_has_replay_session_controls():
    assert 'id="sessions-btn"' in PANEL_HTML
    assert 'id="sessions-panel"' in PANEL_HTML
    assert 'id="replay-controls"' in PANEL_HTML
    assert 'id="replay-badge"' not in PANEL_HTML
    assert "const replayBadge" not in PANEL_HTML


def test_panel_replay_mode_hides_chat_composer():
    replay_ui = PANEL_JS.split("function setReplayUi(active)", 1)[1].split(
        "function replayDelay", 1
    )[0]
    replay_css = PANEL_CSS.split("body.replay-mode footer {", 1)[1].split("}", 1)[0]

    assert "document.body.classList.toggle('replay-mode', active);" in replay_ui
    assert "display: none;" in replay_css
    assert "body.replay-mode footer" in PANEL_CSS
    assert "body.replay-mode .input-shell" not in PANEL_CSS


def test_panel_replay_slider_thumb_is_flat_and_aligned():
    slider_css = PANEL_HTML.split("#replay-slider {", 1)[1].split("}", 1)[0]
    assert "-webkit-appearance: none;" in slider_css
    assert "appearance: none;" in slider_css
    assert "--replay-slider-progress: 0%;" in slider_css
    assert "height: 24px;" in slider_css
    assert "background: linear-gradient(90deg, var(--tds-fill-brand) 0 var(--replay-slider-progress, 0%), var(--tds-grey-300) var(--replay-slider-progress, 0%) 100%);" in slider_css
    assert "background-size: 100% 4px;" in slider_css
    assert "background-position: center;" in slider_css
    assert "box-shadow: none;" in slider_css
    assert "filter: none;" in slider_css

    webkit_track = PANEL_HTML.split("#replay-slider::-webkit-slider-runnable-track {", 1)[1].split("}", 1)[0]
    assert "height: 4px;" in webkit_track
    assert "border-radius: var(--tds-radius-full);" in webkit_track
    assert "background: transparent;" in webkit_track
    assert "box-shadow: none;" in webkit_track

    webkit_thumb = PANEL_HTML.split("#replay-slider::-webkit-slider-thumb {", 1)[1].split("}", 1)[0]
    assert "-webkit-appearance: none;" in webkit_thumb
    assert "appearance: none;" in webkit_thumb
    assert "width: 16px;" in webkit_thumb
    assert "height: 16px;" in webkit_thumb
    assert "margin-top: -6px;" in webkit_thumb
    assert "border: 0;" in webkit_thumb
    assert "box-shadow: none;" in webkit_thumb
    assert "filter: none;" in webkit_thumb

    moz_thumb = PANEL_HTML.split("#replay-slider::-moz-range-thumb {", 1)[1].split("}", 1)[0]
    assert "width: 16px;" in moz_thumb
    assert "height: 16px;" in moz_thumb
    assert "border: 0;" in moz_thumb
    assert "box-shadow: none;" in moz_thumb
    assert "function updateReplaySliderProgress()" in PANEL_HTML
    assert "replaySlider.style.setProperty('--replay-slider-progress', `${progress}%`);" in PANEL_HTML
    assert "updateReplaySliderProgress();" in PANEL_HTML


def test_panel_run_button_toggles_to_stop_and_status_uses_loading_indicator():
    assert 'id="btn"' in PANEL_HTML
    assert 'id="btn-icon-path"' in PANEL_HTML
    assert 'id="stop-btn"' not in PANEL_HTML
    assert 'id="run-loading"' not in PANEL_HTML
    assert 'id="status-loading"' in PANEL_HTML
    assert '@keyframes tds-loading-dots' in PANEL_HTML
    assert '.status-dot.running      { display: none; }' in PANEL_HTML
    assert "statusLoading.classList.toggle('active', state === 'running');" in PANEL_HTML
    assert "fetch('/interrupt', { method: 'POST' })" in PANEL_HTML
    assert "case 'task_interrupted':" in PANEL_HTML
    assert "btn.classList.toggle('stop', stopMode);" in PANEL_HTML
    assert "btnIconPath.setAttribute('d', stopMode ? 'M6 6h12v12H6z' : 'M8 5v14l11-7z');" in PANEL_HTML
    assert "if (isRunning || isSubmitting)" in PANEL_HTML
    assert 'id="replay-slider"' in PANEL_HTML
    assert 'function loadSessions()' in PANEL_HTML
    assert 'async function startReplay(sessionId)' in PANEL_HTML


def test_panel_start_replay_renders_loaded_session_immediately_and_reports_failures():
    start_replay = PANEL_HTML.split("async function startReplay(sessionId)", 1)[1].split(
        "sessionsBtn.addEventListener", 1
    )[0]

    assert "function showReplayMessage(title, detail, cls = 'red')" in PANEL_HTML
    assert "replayTo(replayEvents.length);" in start_replay
    assert "showReplayMessage('No replay events.'" in start_replay
    assert "showReplayMessage('Could not load replay session'" in start_replay
    assert "if (!res.ok) throw new Error(`HTTP ${res.status}`);" in start_replay


def test_panel_disables_live_input_and_ignores_ws_during_replay():
    assert "if (replayMode) return;" in PANEL_HTML
    assert "function setReplayUi(active)" in PANEL_HTML
    assert "setInputEnabled(!active && !isRunning" in PANEL_HTML
    assert "setStatus('connected', 'replay')" not in PANEL_HTML


def test_panel_links_replay_screenshots_from_action_artifacts():
    action_case = PANEL_HTML.split("case 'action_executed':", 1)[1].split(
        "case 'step_error':", 1
    )[0]
    assert "storeArtifactsForStep(ev.step_id, ev.artifacts);" in action_case
    step_render = PANEL_HTML.split("function renderActionStepAdditionalInfo(stepId)", 1)[1].split(
        "function renderTimelineActionStepInfo", 1
    )[0]
    assert "renderActionArtifacts(artifacts, actionContext)" in step_render


def test_panel_uses_toss_design_tokens():
    assert '"Pretendard Variable"' in PANEL_HTML
    assert '"Apple SD Gothic Neo"' in PANEL_HTML
    assert "--tds-fill-brand:        var(--tds-blue-500);" in PANEL_HTML
    assert "--tds-text-primary:      var(--tds-grey-900);" in PANEL_HTML
    assert "--tds-border-secondary:  var(--tds-grey-200);" in PANEL_HTML
    assert "--tds-radius-xl:   16px;" in PANEL_HTML
    assert "--tds-shadow-3:" in PANEL_HTML
    # Legacy aliases preserved for in-file references
    assert "--primary:" in PANEL_HTML
    assert "--surface-1:" in PANEL_HTML
    assert "--radius-lg:" in PANEL_HTML
    assert "--shadow-2:" in PANEL_HTML


def test_panel_uses_toss_light_palette_without_dark_theme_chrome():
    assert "--tds-blue-500:  #3182f6;" in PANEL_HTML
    assert "--tds-grey-900:  #191f28;" in PANEL_HTML
    assert "--tds-grey-100:  #f2f4f6;" in PANEL_HTML
    assert "--tds-white:     #ffffff;" in PANEL_HTML
    assert "color-scheme: light;" in PANEL_HTML
    assert "html[data-theme=\"dark\"]" not in PANEL_HTML
    assert "--app-bg-radial" not in PANEL_HTML
    assert "radial-gradient(circle" not in PANEL_HTML
    assert "Material Design" not in PANEL_HTML
    assert "Material Symbols" not in PANEL_HTML


def test_panel_uses_toss_corner_radius_scale():
    assert "--tds-radius-s:     8px;" in PANEL_HTML
    assert "--tds-radius-m:    12px;" in PANEL_HTML
    assert "--tds-radius-l:    14px;" in PANEL_HTML
    assert "--tds-radius-xl:   16px;" in PANEL_HTML
    assert "--tds-radius-3xl:  24px;" in PANEL_HTML


def test_panel_primary_run_button_uses_toss_icon_button_style():
    assert "#btn {" in PANEL_HTML
    assert "background: var(--tds-fill-brand);" in PANEL_HTML
    assert "color: var(--tds-text-alt);" in PANEL_HTML
    assert 'aria-label="Run task"' in PANEL_HTML
    assert 'title="Run task"' in PANEL_HTML
    assert '<button id="btn" class="icon-only" type="button" aria-label="Run task" title="Run task" disabled>' in PANEL_HTML
    assert "<svg class=\"btn-icon\" aria-hidden=\"true\" viewBox=\"0 0 24 24\" focusable=\"false\">" in PANEL_HTML
    assert '<path id="btn-icon-path" d="M8 5v14l11-7z"></path>' in PANEL_HTML
    button_css = PANEL_HTML.split("#btn {", 1)[1].split("#btn .btn-icon", 1)[0]
    assert "width: 40px;" in button_css
    assert "min-width: 40px;" in button_css
    assert "height: 40px;" in button_css
    assert "padding: 0;" in PANEL_HTML
    assert "<button id=\"btn\" type=\"button\" disabled>run</button>" not in PANEL_HTML




def test_panel_header_controls_use_shared_header_order():
    header_html = PANEL_HTML.split("<header>", 1)[1].split("</header>", 1)[0]

    live_idx = header_html.index('id="live-btn"')
    sessions_idx = header_html.index('id="sessions-btn"')

    assert live_idx < sessions_idx
    assert 'id="theme-toggle"' not in header_html
    assert '"header       header       header  header        header"' in PANEL_HTML
    assert 'class="sheet-header"' not in PANEL_HTML

def test_panel_secondary_controls_use_svg_icons_with_accessible_labels():
    assert 'id="sessions-btn" class="icon-label" type="button" aria-label="Open history"' in PANEL_HTML
    assert '<span>History</span>' in PANEL_HTML
    assert 'id="live-btn" class="icon-label" type="button" aria-label="Start new live view"' in PANEL_HTML
    assert '<span>New</span>' in PANEL_HTML
    assert '<path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"></path>' in PANEL_HTML
    assert 'id="sessions-close" class="icon-only" type="button" aria-label="Close History"' in PANEL_HTML
    assert 'id="replay-prev" class="icon-only" type="button" aria-label="Previous replay step"' in PANEL_HTML
    assert 'id="replay-play" class="icon-only" type="button" aria-label="Play or pause replay"' in PANEL_HTML
    assert 'id="replay-next" class="icon-only" type="button" aria-label="Next replay step"' in PANEL_HTML
    assert 'class="view-tab icon-label active" data-view="timeline"' in PANEL_HTML
    assert 'class="view-tab icon-label" data-view="graph"' in PANEL_HTML
    assert 'btn.className = \'session-item\';' in PANEL_HTML
    assert "<button id=\"sessions-close\" type=\"button\">×</button>" not in PANEL_HTML
    assert "<button id=\"replay-prev\" type=\"button\">⏮</button>" not in PANEL_HTML
    assert "<button id=\"replay-play\" type=\"button\">⏯</button>" not in PANEL_HTML
    assert "<button id=\"replay-next\" type=\"button\">⏭</button>" not in PANEL_HTML
    assert "`▶ ${escHtml(session.id)}" not in PANEL_HTML


def test_panel_history_drawer_styles_are_available():
    assert "#sessions-panel.sessions-drawer {" in PANEL_CSS
    assert "#sessions-panel.sessions-drawer.hidden {" in PANEL_CSS
    assert ".sessions-search {" in PANEL_CSS
    assert ".sessions-body {" in PANEL_CSS
    assert ".sessions-message {" in PANEL_CSS
    assert ".session-date-group {" in PANEL_CSS
    assert ".session-date-group h3 {" in PANEL_CSS
    assert ".session-main-row {" in PANEL_CSS
    assert ".session-primary {" in PANEL_CSS
    assert ".session-current-marker {" in PANEL_CSS
    assert ".session-meta {" in PANEL_CSS
    assert ".session-meta .session-artifact-badge {" in PANEL_CSS
    assert ".session-date-tag {" not in PANEL_CSS
    assert ".session-metrics {" not in PANEL_CSS


def test_panel_history_session_items_render_query_first_rows():
    render_session_button = PANEL_JS.split("function renderSessionButton(session)", 1)[1].split(
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
    assert 'class="session-title-row"' not in PANEL_JS
    assert 'class="session-date-tag' not in PANEL_JS
    assert 'class="session-query"' not in PANEL_JS
    assert 'class="session-metrics"' not in PANEL_JS
    assert 'trajectory</span>' not in render_session_button
    assert 'class="btn-icon"' not in render_session_button
    assert "M8 5v14l11-7z" not in render_session_button
    assert "▶" not in render_session_button


def test_panel_history_session_meta_labels_count_as_actions():
    # step_count counts executed actions (one history/step-NNNN.json per action),
    # so the history-drawer label reads "actions", not "steps".
    session_meta = PANEL_JS.split("function sessionMetaHtml(session)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "${escHtml(session.step_count || 0)} actions</span>" in session_meta
    assert " steps</span>" not in session_meta


def test_panel_sessions_panel_closes_on_outside_click_and_escape():
    assert "function closeSessionsPanel()" in PANEL_JS
    assert "function isSessionsPanelTarget(target)" in PANEL_JS
    assert "document.addEventListener('pointerdown', (event) => {" in PANEL_JS
    assert "if (isSessionsPanelTarget(event.target)) return;" in PANEL_JS
    assert "closeSessionsPanel();" in PANEL_JS
    assert "document.addEventListener('keydown', (event) => {" in PANEL_JS
    assert "if (event.key === 'Escape') closeSessionsPanel();" in PANEL_JS


def test_panel_graph_tracks_global_url_sequence():
    # Global URL nav order is needed for layer-1 cue detection.
    assert "let urlSequence = [];" in PANEL_HTML
    record_nav = PANEL_HTML.split("function recordNavigation(url, stepId)", 1)[1].split(
        "function recordActionExecution", 1
    )[0]
    assert "urlSequence.push(key);" in record_nav
    reset_fn = PANEL_HTML.split("function resetTrajectoryGraphState()", 1)[1].split(
        "function ", 1
    )[0]
    assert "urlSequence.length = 0;" in reset_fn or "urlSequence = [];" in reset_fn


def test_panel_graph_compute_own_cues_emits_three_motif_types():
    # Cue function emits only the three supported motif types:
    # repeated node, loop edge, and no-op action.
    assert "function computeOwnCues(type, node, cyclicSet)" in GRAPH_JS
    body = GRAPH_JS.split("function computeOwnCues(type, node, cyclicSet)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    for key in ("cycle", "repeated", "noop"):
        assert f"{key}," in body or f"{key}:" in body, f"missing cue key {key}"
    assert "deadEnd" not in body
    # Cycle membership is set-driven (SCC), not a fragile A→B→A bounce.
    assert "cyclicSet.has(node.id)" in body
    # Repeated is amber (own attention but not red).
    assert "'amber'" in body
    assert "'red'" in body
    # noop is action-only.
    assert "type === 'action'" in body and "noopFlag(node)" in body
    assert "isDeadEndCandidate" not in GRAPH_JS


def test_panel_graph_cycle_detection_reused_from_scc():
    # P2: detectCycleEdges must delegate to the extracted SCC helper so cue
    # computation and edge highlighting share the same definition of cycle.
    assert "function computeCyclicNodes(links)" in GRAPH_JS
    detect_body = GRAPH_JS.split("function detectCycleEdges(links) {", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "computeCyclicNodes(links)" in detect_body


def test_panel_graph_build_cue_context_precomputes_layer_cyclic_sets():
    body = GRAPH_JS.split("function buildCueContext()", 1)[1].split(
        "\nfunction ", 1
    )[0]
    # Three layer-specific cyclic sets seed cue computation.
    assert "urlCyclic" in body
    assert "viewportCyclicByUrl" in body
    assert "actionCyclicByViewport" in body
    assert "computeCyclicNodes(" in body
    # Outcome metadata no longer creates a dead-end cue.
    assert "trajectoryOutcome" not in body


def test_panel_graph_rollup_breakdown_covers_three_motif_types():
    body = GRAPH_JS.split("function rollupCueFor(type, scope, context)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    # Internal rollup breakdown still tracks all motif types.
    for key in ("cycle:", "repeated:", "noop:"):
        assert key in body
    assert "deadEnd:" not in body
    # Badges surface every collapsed lower-layer cue, including repeated
    # descendants whose own node size/color encoding is hidden by collapse.
    assert "const BADGE_CUE_TYPES = ['cycle', 'repeated', 'noop'];" in GRAPH_JS
    assert "if (BADGE_CUE_TYPES.includes(cueType)) count += 1;" in body
    assert "deadEnd" not in body
    # URL badges summarize hidden viewport and action descendants.
    assert "scope.viewportIds" in body
    assert "scope.actionIds" in body


def test_panel_graph_builders_attach_cue_fields():
    for fn in ("buildUrlGraphData", "buildViewportGraphData", "buildActionGraphData"):
        body = GRAPH_JS.split(f"function {fn}", 1)[1].split(
            "\nfunction ", 1
        )[0]
        assert "buildCueContext()" in body or "cueContext" in body, f"{fn} must use cue context"
        assert "attachCueFields" in body, f"{fn} must attach cue fields"
    # Cue lookup goes through the cached ownCuesById map, not a recomputation.
    attach_body = GRAPH_JS.split("function attachCueFields(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "context.ownCuesById.get(src.id)" in attach_body
    assert "badgeCount" in attach_body
    # Badge principle: own-layer cues already visible in the current graph layer
    # must not inflate badgeCount. Badges summarize lower layers only.
    assert "badgeCount = rollupCount" in attach_body
    assert "ownRedCount" not in attach_body


def test_panel_graph_dominant_cue_priority_ordering():
    # Outline §S2 badge principle: an own-layer cue with another visual channel
    # must NOT also appear in the badge.
    #   repeated → encoded by node fill+radius
    #   cycle    → encoded by edge highlight
    #   noop     → encoded by cue-ring stroke (no-op outline) plus detail-panel evidence
    # Rollup badges surface every cue type named by outline §S2 examples so
    # collapsed parents advertise descendant cues hidden by collapse.
    rollup_decl = GRAPH_JS.split("const ROLLUP_CUE_PRIORITY =", 1)[1].split(";", 1)[0]
    for included in ("'cycle'", "'repeated'", "'noop'"):
        assert included in rollup_decl, f"{included} should surface collapsed lower-layer cues"
    assert "'deadEnd'" not in rollup_decl
    glyph_decl = GRAPH_JS.split("const CUE_GLYPH =", 1)[1].split(";", 1)[0]
    assert "repeated" in glyph_decl
    assert "const CUE_PRIORITY" not in GRAPH_JS
    assert "dominantOwnCueType" not in GRAPH_JS


def test_panel_graph_badges_are_rollup_only():
    # Outline §S2: badges summarize collapsed lower-layer cues only. Action
    # nodes have no lower layer, so own action cues are not rendered as badges.
    badge_body = GRAPH_JS.split("function cueBadgeClass(d)", 1)[1].split("}\n", 1)[0]
    assert "ownType" not in badge_body
    assert "dominantOwnCueType" not in badge_body
    assert "rollupType" in badge_body
    # Badge exposes a glyph and a cue-type class.
    assert "cue-${" in badge_body or "cue-${rollupType}" in badge_body
    assert "CUE_GLYPH" in GRAPH_JS


def test_panel_graph_renders_cue_ring_on_nodes():
    # Cue-ring SVG element is appended on enter and reflects no-op cues.
    update_body = GRAPH_JS.split("function update(payload) {", 1)[1].split(
        "\n  function reset()", 1
    )[0]
    assert "'cue-ring'" in update_body
    assert "ownCueRingType(d)" in update_body
    ring_body = GRAPH_JS.split("function ownCueRingType(d)", 1)[1].split("\nfunction ", 1)[0]
    assert "d.ownCues.noop" in ring_body
    assert "deadEnd" not in ring_body
    # Badge label combines glyph + count once count ≥ 2.
    assert "d.badgeCount >= 2" in update_body


def test_panel_css_cue_ring_and_typed_badge_styles():
    for token in (
        "--graph-accent-noop:     var(--tds-fill-danger);",
        "--graph-accent-current:  var(--tds-fill-brand);",
        "--graph-accent-selected: var(--tds-fill-warning);",
        "--graph-accent-running:  var(--tds-fill-warning);",
        "--graph-accent-cycle:    var(--tds-fill-danger);",
        "--graph-accent-repeated: var(--tds-fill-warning);",
    ):
        assert token in PANEL_CSS
    assert "--graph-accent-dead-end:" not in PANEL_CSS
    for sel in (
        ".graph-node circle.cue-ring",
        ".graph-node circle.cue-ring.cue-noop",
        ".graph-node .graph-node-cue-shape",
        ".graph-node .graph-node-cue-shape.cue-noop",
        ".cue-legend-swatch.cue-cycle-edge",
        ".cue-legend-swatch.cue-noop",
        ".node-cue-badge circle.cue-cycle",   # rollup badge for cycle still needed
        ".node-cue-badge circle.cue-repeated",
        ".node-cue-badge circle.cue-noop",
    ):
        assert sel in PANEL_CSS, f"missing css rule: {sel}"
    for absent in (
        ".graph-node circle.cue-ring.cue-deadEnd",
        ".graph-node .graph-node-cue-shape.cue-deadEnd",
        ".graph-node .graph-node-cue-shape.cue-repeated",
        ".graph-node .graph-node-cue-shape.cue-cycle",
        ".cue-legend-swatch.cue-deadEnd",
        ".cue-legend-swatch.cue-repeated",
        ".node-cue-badge circle.cue-deadEnd",
    ):
        assert absent not in PANEL_CSS, f"unexpected cue css rule: {absent}"
    # Cues that have another visual channel get no ring.
    for absent in (
        ".graph-node circle.cue-ring.cue-repeated",
        ".graph-node circle.cue-ring.cue-cycle",
    ):
        assert absent not in PANEL_CSS, f"unexpected css rule: {absent}"
    noop_badge_rule = re.search(
        r"\.node-cue-badge circle\.cue-noop\s*\{([^}]*)\}",
        PANEL_CSS,
    )
    assert noop_badge_rule
    assert "fill: var(--graph-accent-cycle);" in noop_badge_rule.group(1)
    assert "stroke: none;" in noop_badge_rule.group(1)
    assert "stroke-width:" not in noop_badge_rule.group(1)
    noop_legend_rule = re.search(
        r"\.cue-legend-swatch\.cue-noop\s*\{([^}]*)\}",
        PANEL_CSS,
    )
    assert noop_legend_rule
    assert "background:" not in noop_legend_rule.group(1)
    assert "border: 4px solid var(--graph-accent-noop);" in noop_legend_rule.group(1)
    noop_ring_rule = re.search(
        r"\.graph-node circle\.cue-ring\.cue-noop\s*\{([^}]*)\}",
        PANEL_CSS,
    )
    assert noop_ring_rule
    assert "stroke: var(--graph-accent-noop);" in noop_ring_rule.group(1)
    assert "fill:" not in noop_ring_rule.group(1)
    assert ".node-cue-badge text.on-outline" not in PANEL_CSS
    assert "textClass: 'on-stroke'" in GRAPH_JS
    assert "rollupType === 'noop' ? 'on-outline' : 'on-stroke'" not in GRAPH_JS


def test_noop_alert_renders_above_compare_when_isnoop():
    # Outline §F2.4: no-op outcome cue surfaces as a banner above the
    # before/after compare only after DOM, ARIA, and screenshot evidence all
    # satisfy the <= K no-change threshold.
    body = GRAPH_JS.split("function renderActionArtifacts(artifacts", 1)[1].split(
        "\nfunction ", 1
    )[0]
    # No longer accepts/trusts caller-supplied isNoop or same screenshot path alone.
    assert "function renderActionArtifacts(artifacts, actionContext = null)" in GRAPH_JS
    assert "isNoopDetectionEligibleAction(actionContext)" in body
    assert "beforeShot === afterShot" not in body
    # Renders the alert class above artifact-compare (cards array order).
    assert "artifact-noop-alert" in body
    assert 'hidden data-noop-evidence="true"' in body
    assert "Checking no-op evidence" in body
    compare_pos = body.find("renderBeforeAfterCompare(beforeShot, afterShot)")
    alert_pos = body.find("noopAlert,")
    assert 0 < alert_pos < compare_pos, "noop alert must precede compare in cards array"
    assert "hydrateNoopEvidence(sideReplay);" in PANEL_JS
    assert "hydrateNoopEvidence(replayEl);" in GRAPH_JS


def test_noop_alert_css_present():
    assert ".artifact-noop-alert" in PANEL_CSS
    assert ".artifact-noop-alert[hidden]" in PANEL_CSS
    assert ".artifact-noop-text" in PANEL_CSS


def test_p5_action_node_carries_aria_signatures_without_raw_text():
    # Raw ARIA text is intentionally not retained in action graph nodes. The
    # graph keeps compact signatures for structural cues, while detailed ARIA
    # evidence remains available through lazy artifact previews.
    record_body = GRAPH_JS.split("function recordActionExecution(ev)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "postAriaSig = ariaDiffSignature((ev.artifacts && ev.artifacts.aria_snapshot) || '')" in record_body
    assert "preAriaSig: preSnap ? preSnap.ariaSig : null" in record_body
    assert "postAriaSig," in record_body
    assert "ariaText:" not in record_body


def test_p5_aria_pre_post_diff_renderer_is_set_based():
    helper = GRAPH_JS.split("function ariaDiffLines(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    # Removals and additions derive from set membership.
    assert "preSet = new Set(preLines)" in helper
    assert "postSet = new Set(postLines)" in helper
    assert "kind: 'removed'" in helper
    assert "kind: 'added'" in helper
    # Truncated flag prevents the panel from rendering pathologically long diffs.
    assert "truncated = true" in helper
    renderer = GRAPH_JS.split("function renderAriaPrePostDiff(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "ariaDiffLines(preText, postText)" in renderer
    assert "aria-diff-line" in renderer
    assert "ARIA diff" in renderer


def test_p5_browser_state_body_uses_lazy_dom_and_aria_artifact_previews():
    dom_body = GRAPH_JS.split("function renderDomStateBody(artifacts, actionNode)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    aria_body = GRAPH_JS.split("function renderAriaStateBody(artifacts, actionNode)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "renderAriaPrePostDiff(actionNode.preAriaText, actionNode.postAriaText)" not in dom_body
    assert "renderBrowserStatePreview('DOM snapshot', state.domHref, 'DOM')" in dom_body
    assert "renderBrowserStatePreview('ARIA snapshot', state.ariaHref, 'ARIA')" not in dom_body
    assert "renderBrowserStatePreview('DOM snapshot', state.domHref, 'DOM')" not in aria_body
    assert "renderBrowserStatePreview('ARIA snapshot', state.ariaHref, 'ARIA')" in aria_body
    browser_preview = GRAPH_JS.split("function renderBrowserStatePreview(title, href, kind)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "return renderCodeBox(title" in browser_preview
    assert "data-browser-state-src" in GRAPH_JS


def test_p5_before_after_slider_uses_clip_path_split():
    renderer = GRAPH_JS.split("function renderBeforeAfterCompare(beforeHref, afterHref)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "artifact-slider" in renderer
    assert "--split" in renderer
    assert "artifact-slider-before" in renderer
    assert "artifact-slider-after" in renderer
    assert "type=\"range\"" in renderer
    # CSS implements the actual reveal.
    assert ".artifact-slider .artifact-slider-after" in PANEL_CSS
    assert "clip-path: inset(0 0 0 var(--split" in PANEL_CSS


def test_p5_noop_alert_requires_dom_aria_and_screenshot_thresholds():
    renderer = GRAPH_JS.split("function renderBeforeAfterCompare(beforeHref, afterHref)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "artifact-visual-diff" not in renderer
    assert "Visual diff" not in renderer
    helper = GRAPH_JS.split("function hydrateNoopEvidence(root = document)", 1)[1].split(
        "\n// Set-based ARIA diff", 1
    )[0]
    assert "NOOP_EVIDENCE_DIFF_THRESHOLD = 0.01" in GRAPH_JS
    assert "function evaluateNoopEvidence(artifacts)" in GRAPH_JS
    assert "function primeNoopEvidenceForAction(actionNode)" in GRAPH_JS
    assert ".artifact-noop-alert[data-noop-evidence]:not([data-noop-ready])" in helper
    evidence_helper = GRAPH_JS.split("function evaluateNoopEvidence(artifacts)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "fetchArtifactTextByName(paths.beforeHtml)" in evidence_helper
    assert "fetchArtifactTextByName(paths.afterHtml)" in evidence_helper
    assert "fetchArtifactTextByName(paths.beforeAria)" in evidence_helper
    assert "fetchArtifactTextByName(paths.afterAria)" in evidence_helper
    assert "screenshotDiffRatio(" in evidence_helper
    assert "domRatio === 0" in evidence_helper
    assert "ariaRatio === 0" in evidence_helper
    assert "screenshotRatio <= NOOP_EVIDENCE_DIFF_THRESHOLD" in evidence_helper
    screenshot_helper = GRAPH_JS.split("function screenshotDiffRatio(beforeSrc, afterSrc)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "getImageData(0, 0, w, h)" in screenshot_helper
    assert "changedPixels" in screenshot_helper
    assert "window.hydrateNoopEvidence = hydrateNoopEvidence;" in GRAPH_JS
    prime_body = GRAPH_JS.split("function primeNoopEvidenceForAction(actionNode)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "!isNoopDetectionEligibleAction(actionNode)" in prime_body
    assert "actionNode.noopEvidenceStatus = 'skipped'" in prime_body
    assert "actionNode.noopEvidenceKey = evidenceKey" in prime_body
    assert "actionNode.noopEvidenceStatus = evidence.ok ? 'pass' : 'fail'" in prime_body
    assert "scheduleGraphUpdate();" in prime_body


def test_noop_detection_excludes_observe_and_wait_actions():
    assert "function isNoopDetectionExcludedAction(actionName)" in GRAPH_JS
    assert "function isNoopDetectionEligibleAction(actionNode)" in GRAPH_JS

    exclude_body = GRAPH_JS.split("function isNoopDetectionExcludedAction(actionName)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "name.startsWith('observe')" in exclude_body
    assert "name.startsWith('wait')" in exclude_body

    eligible_body = GRAPH_JS.split("function isNoopDetectionEligibleAction(actionNode)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "!isNoopDetectionExcludedAction(actionNode.actionName)" in eligible_body

    noop_body = GRAPH_JS.split("function noopFlag(actionNode)", 1)[1].split("\nfunction ", 1)[0]
    assert "isNoopDetectionEligibleAction(actionNode)" in noop_body
    assert "noopEvidenceStatus === 'pass'" in noop_body

    step_render = PANEL_HTML.split("function renderActionStepAdditionalInfo(stepId)", 1)[1].split(
        "function renderTimelineActionStepInfo", 1
    )[0]
    assert "const actionContext = actionNode ||" in step_render
    assert "renderActionArtifacts(artifacts, actionContext)" in step_render

    group_render = PANEL_HTML.split("function renderActionGroupAdditionalInfo(actionNode)", 1)[1].split(
        "window.renderActionGroupAdditionalInfo", 1
    )[0]
    assert "renderActionArtifacts(artifacts, actionNode)" in group_render

    graph_node_selection = GRAPH_JS.split("function renderGraphNodeSelection(d)", 1)[1].split(
        "function renderSelection", 1
    )[0]
    assert "renderActionArtifacts(d.artifacts, d)" in graph_node_selection


def test_p5_aria_diff_styles_and_truncation_hint():
    for sel in (
        ".aria-diff",
        ".aria-diff-line.added",
        ".aria-diff-line.removed",
        ".aria-diff-prefix",
        ".aria-diff-truncated",
    ):
        assert sel in PANEL_CSS, f"missing diff style: {sel}"
    assert ".artifact-visual-diff" not in PANEL_CSS


def test_graph_cue_legend_pinned_bottom_right_with_motif_and_highlight_rows():
    # Legend reflects only the supported cue encodings:
    #   loop     → edge path marker
    #   no-op    → action anchor marker
    # Repeated nodes are already encoded by node size and color intensity, so
    # the cue legend does not duplicate that row.
    assert 'id="graph-cue-legend"' in PANEL_HTML_ONLY
    assert 'aria-label="Graph cue and node highlight legend"' in PANEL_HTML_ONLY
    assert 'data-cue="repeated"' not in PANEL_HTML_ONLY
    assert 'cue-legend-swatch cue-repeated' not in PANEL_HTML_ONLY
    assert '>repeated node<' not in PANEL_HTML_ONLY
    assert 'data-cue="cycle"' in PANEL_HTML_ONLY
    assert 'cue-legend-swatch cue-cycle-edge' in PANEL_HTML_ONLY
    assert '>loop edge<' in PANEL_HTML_ONLY
    assert 'data-cue="deadEnd"' not in PANEL_HTML_ONLY
    assert 'cue-legend-swatch cue-deadEnd' not in PANEL_HTML_ONLY
    assert '<span class="cue-legend-glyph" aria-hidden="true">■</span>' not in PANEL_HTML_ONLY
    assert '>dead end<' not in PANEL_HTML_ONLY
    assert 'data-cue="noop"' in PANEL_HTML_ONLY
    assert 'cue-legend-swatch cue-noop' in PANEL_HTML_ONLY
    assert '>no-op<' in PANEL_HTML_ONLY
    for absent in ('data-cue="currentNode"', 'data-cue="selectedNode"'):
        assert absent not in PANEL_HTML_ONLY, f'{absent} should be removed from legend'
    assert '>current node<' not in PANEL_HTML_ONLY
    assert '>selected node<' not in PANEL_HTML_ONLY
    for cue_class in ('cue-cycle-edge', 'cue-noop'):
        cue_rule = re.search(
            rf"\.cue-legend-swatch\.{cue_class}\s*\{{([^}}]*)\}}",
            PANEL_CSS,
        )
        assert cue_rule
        assert any(prop in cue_rule.group(1) for prop in ('border:', 'background:', 'border-top:'))
    # Pinned to bottom-right.
    css_block = PANEL_CSS.split('.graph-cue-legend {', 1)[1].split('}', 1)[0]
    assert 'bottom: 14px' in css_block
    assert 'right: 14px' in css_block
    # Show/hide piggy-backs on the existing updateGraphLegend trigger so the
    # legend appears only after the first node is rendered.
    legend_update = GRAPH_JS.split('function updateGraphLegend(maxVisitCount, hasNodes)', 1)[1].split(
        '\n  function ', 1
    )[0]
    assert 'cueLegendEl.classList.toggle' in legend_update


def test_p5_panel_threads_action_node_into_auxiliary_sections():
    assert "window.actionNodeForStep = actionNodeForStep;" in GRAPH_JS
    assert "function actionNodeForStep(stepId)" in GRAPH_JS
    # Step-level selector resolves the action node before rendering.
    step_render = PANEL_JS.split("function renderActionStepAdditionalInfo(stepId)", 1)[1].split(
        "function actionGroupStepIds", 1
    )[0]
    assert "window.actionNodeForStep(key)" in step_render


def test_panel_dispatches_setTrajectoryOutcome_on_task_lifecycle_events():
    # P3: panel.js must forward outcome metadata from the WebSocket terminal
    # events into the graph for terminal-state consumers.
    body = PANEL_JS
    for case_key, success in (
        ("case 'task_complete':", "taskSuccess: true"),
        ("case 'task_failed':", "taskSuccess: false"),
        ("case 'task_interrupted':", "taskSuccess: false"),
    ):
        # Each terminal-event handler invokes the global setter with the right success flag.
        chunk = body.split(case_key, 1)[1].split("break;", 1)[0]
        assert "dispatchTrajectoryOutcome" in chunk, f"{case_key} missing outcome dispatch"
        assert success in chunk, f"{case_key} missing {success}"
        assert "terminalStepId: ev.terminal_step_id" in chunk
    assert "window.setTrajectoryOutcome(outcome);" in body
    # Setter is exported on the window from graph.js so panel.js can call it.
    assert "window.setTrajectoryOutcome = setTrajectoryOutcome;" in GRAPH_JS


def test_panel_graph_trajectory_outcome_stub_present():
    # P2 declares the outcome holder; P3 fills it. Reset must clear it.
    assert "let trajectoryOutcome" in GRAPH_JS
    assert "function setTrajectoryOutcome(" in GRAPH_JS
    reset_body = GRAPH_JS.split("function resetTrajectoryGraphState() {", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "trajectoryOutcome = null;" in reset_body


def test_panel_graph_renders_cue_badge_with_severity_matrix():
    update_body = PANEL_HTML.split("function update(payload) {", 1)[1].split(
        "function reset()", 1
    )[0]
    # Badge group is attached on enter
    assert ".node-cue-badge" in update_body
    assert "g').attr('class', 'node-cue-badge'" in update_body or 'class\', \'node-cue-badge\'' in update_body
    # Badge visibility gated on badgeCount > 0
    assert "d.badgeCount > 0" in update_body or "d.badgeCount >= 1" in update_body
    # Badge severity is rollup-only; own-layer cues use primary encodings.
    assert "own-red" not in update_body
    assert "rollup-red" in update_body
    # Rollup badges use one readable text style over their cue-specific badge.
    assert "on-fill" not in update_body
    assert "on-stroke" in update_body


def test_panel_graph_tooltip_includes_cue_breakdown():
    tooltip_block = GRAPH_JS.split("function graphTooltipHtml(d) {", 1)[1].split(
        "function positionGraphTooltip", 1
    )[0]
    # Section header + per-type rows for visible cue badges.
    assert "Cues" in tooltip_block
    for label in ("cycle", "repeated", "no-op"):
        assert label in tooltip_block
    assert "dead end" not in tooltip_block
    # own / inside split preserved.
    assert "own" in tooltip_block
    assert "inside" in tooltip_block
    # Guarded: only renders when something to show
    assert "d.badgeCount" in tooltip_block or "d.ownCues" in tooltip_block


def test_panel_left_sidebar_always_shows_task_status_and_plan():
    left_html = PANEL_HTML_ONLY.split('<aside id="left-sidebar"', 1)[1].split("</aside>", 1)[0]
    right_html = PANEL_HTML_ONLY.split('<aside id="right-sidebar"', 1)[1].split("</aside>", 1)[0]

    assert '<aside id="left-sidebar" class="side-panel" aria-label="Session details">' in PANEL_HTML_ONLY
    assert '<aside id="right-sidebar" class="side-panel" aria-label="Additional action information">' in PANEL_HTML_ONLY
    assert 'class="side-section side-scroll-section side-task-section"' in PANEL_HTML
    assert 'class="side-section side-scroll-section side-plan-section"' in PANEL_HTML
    assert '<summary data-icon="task_alt">Task</summary>' in left_html
    assert '<summary data-icon="monitor_heart">Status</summary>' in left_html
    assert '<summary data-icon="route">Plan</summary>' in left_html
    assert '<summary data-icon="ads_click">Additional Info</summary>' in right_html
    assert "data-side-view" not in PANEL_HTML_ONLY
    assert 'class="side-section side-scroll-section side-activity-section"' not in PANEL_HTML
    assert 'id="side-activity"' not in PANEL_HTML
    assert "details.side-scroll-section[open]" in PANEL_HTML
    assert "details.side-scroll-section > .side-body" not in PANEL_HTML


def test_panel_plan_status_uses_icons_instead_of_text_markers():
    render_plan = PANEL_HTML.split("function renderPlan()", 1)[1].split(
        "function upsertActionSummary", 1
    )[0]

    assert "const statusIcons = {" in render_plan
    assert '<span class="status-icon">' in render_plan
    assert "<svg aria-hidden=\"true\"" in render_plan
    for marker in ("[ ]", "[›]", "[✓]", "[✗]"):
        assert marker not in render_plan


def test_panel_plan_items_jump_to_subgoal_start_rows():
    render_plan = PANEL_HTML.split("function renderPlan()", 1)[1].split(
        "function upsertActionSummary", 1
    )[0]
    subgoal_started_case = PANEL_HTML.split("case 'subgoal_started':", 1)[1].split(
        "case 'subgoal_completed':", 1
    )[0]

    assert "let subgoalStartRowsById = new Map();" in PANEL_HTML
    assert "function recordSubgoalStart(subgoalId, row)" in PANEL_HTML
    assert "function jumpToSubgoalStart(subgoalId)" in PANEL_HTML
    assert "function flashSubgoalStartRow(row)" in PANEL_HTML
    assert "subgoalStartRowsById.set(key, row);" in PANEL_HTML
    assert "row.dataset.subgoalId = key;" in PANEL_HTML
    assert "row.scrollIntoView({ block: 'center', behavior: 'smooth' });" in PANEL_HTML
    assert "activateMainView('timeline', { scrollSelection: false });" in PANEL_HTML
    assert 'type="button" class="todo ${sg.status}${jumpable ? \' jumpable\' : \'\'}"' in render_plan
    assert 'data-subgoal-id="${escHtml(key || \'\')}"' in render_plan
    assert "sidePlan.querySelectorAll('[data-subgoal-id]').forEach" in render_plan
    assert "jumpToSubgoalStart(item.getAttribute('data-subgoal-id'))" in render_plan
    assert "recordSubgoalStart(" in subgoal_started_case
    assert "addRow('', `<span style=\"color:var(--orange)\">▸</span> subgoal" in subgoal_started_case
    assert ".row.subgoal-anchor.subgoal-jump-highlight" in PANEL_HTML
    assert "@keyframes subgoal-jump-highlight-fade" in PANEL_HTML
    assert "row.addEventListener('animationend'" in PANEL_HTML
    assert "selectedSubgoalId" not in PANEL_HTML
    assert ".todo.jumpable:hover" in PANEL_HTML


def test_panel_graph_uses_top_down_tree_targets():
    graph_renderer = GRAPH_JS

    assert "function graphRootPosition(" in graph_renderer
    assert "function arrangeGraphNodes(" in graph_renderer
    assert "const GRAPH_TREE_LAYER_SPACING = 96;" in graph_renderer
    assert "const GRAPH_TREE_SIBLING_SPACING = 118;" in graph_renderer
    assert "function buildTopDownLayoutTargets(nodes, linksData, graphMode)" in graph_renderer
    assert "const acyclicLinks = linksData.filter(e => !e.isCycleEdge);" in graph_renderer
    assert "const layoutTargets = buildTopDownLayoutTargets(nodes, linksData, graphMode);" in graph_renderer
    assert "const target = layoutTargets.get(node.id) || { x: 0, y: 90 };" in graph_renderer
    assert "node._targetX = target.x;" in graph_renderer
    assert "node._targetY = target.y;" in graph_renderer
    assert "d3.forceCollide(34).strength(1)" in graph_renderer
    assert "d3.forceManyBody().strength(-160)" in graph_renderer


def test_panel_graph_linear_acyclic_trajectory_targets_single_vertical_column():
    graph_renderer = GRAPH_JS

    assert "function isLinearAcyclicGraph(nodes, acyclicLinks, linksData)" in graph_renderer
    assert "if (isLinearAcyclicGraph(orderedNodes, acyclicLinks, linksData))" in graph_renderer
    assert "{ x: 0, y: topY + index * GRAPH_TREE_LAYER_SPACING }" in graph_renderer
    assert "const orderedNodes = [...nodes].sort((a, b) => {" in graph_renderer
    assert "const bySequence = (a._sequenceIndex || 0) - (b._sequenceIndex || 0);" in graph_renderer


def test_panel_graph_arranges_with_current_render_links():
    update_body = PANEL_HTML.split("function update(payload) {", 1)[1].split(
        "function reset()", 1
    )[0]

    assert update_body.index("linksData = incomingLinks.map(e => ({ ...e, mode: payload.mode }));") < update_body.index(
        "arrangeGraphNodes(nodesData, prevById, linksData, graphMode);"
    )


def test_panel_graph_root_pin_stays_available_for_root_nodes():
    graph_renderer = GRAPH_JS

    assert "x: graphMode === 'url' ? (index - (count - 1) / 2) * 140 : 0," in graph_renderer
    assert "y: graphMode === 'url' ? -180 : -220," in graph_renderer
    assert "node.fx = pinned.x;" in graph_renderer
    assert "node.fy = pinned.y;" in graph_renderer
    assert "if (d && Number.isFinite(d._targetY)) return d._targetY;" in graph_renderer
    assert "d3.forceCollide(34).strength(1)" in graph_renderer
    assert "d3.forceManyBody().strength(-160)" in graph_renderer
    assert "if (d.isRoot) {" in graph_renderer


def test_panel_graph_breadcrumb_uses_layer_stack_and_clears_context_on_return():
    breadcrumb_renderer = PANEL_HTML.split("function renderBreadcrumb(payload)", 1)[1].split(
        "function update(payload)", 1
    )[0]
    selector = PANEL_HTML.split("function selectGraphActionForStep(stepId)", 1)[1].split(
        "function updateGraphSelectionClass", 1
    )[0]

    assert "function layerName(level)" in PANEL_HTML
    assert "return 'URL layer';" in PANEL_HTML
    assert "return 'Viewport layer';" in PANEL_HTML
    assert "return 'Action layer';" in PANEL_HTML
    assert '<span class="sep">›</span>' in breadcrumb_renderer
    assert '<span class="current-layer">' in breadcrumb_renderer
    assert '<span class="parent-label">inside' in breadcrumb_renderer
    assert "setGraphDrilldown({ level: 'url', urlId: null, viewportId: null });" in breadcrumb_renderer
    assert "setGraphDrilldown({ level: 'viewport', urlId: crumb.urlId, viewportId: null });" in breadcrumb_renderer
    assert "function setGraphDrilldown(next)" in PANEL_HTML
    assert "clearGraphDrillAnchor();" in PANEL_HTML.split("function setGraphDrilldown(next)", 1)[1].split("// ── d3 graph renderer", 1)[0]
    assert "clearGraphDrillAnchor();" in selector
    assert "breadcrumbEl.innerHTML = '<span>URL layer</span>';" in PANEL_HTML



def test_panel_graph_updates_are_deferred_when_graph_tab_is_hidden():
    action_recorder = PANEL_HTML.split("function recordActionExecution(ev)", 1)[1].split(
        "function buildSequentialLinks", 1
    )[0]
    update_fn = PANEL_HTML.split("function updateGraph({ force = false } = {})", 1)[1].split(
        "function scheduleGraphUpdate()", 1
    )[0]
    activate_view = PANEL_HTML.split("function activateMainView(view, options = {})", 1)[1].split(
        "(function setupTabs()", 1
    )[0]

    assert "let graphRenderDirty = false;" in PANEL_HTML
    assert "scheduleGraphUpdate();" in action_recorder
    assert "function isGraphViewActive()" in PANEL_HTML
    assert "document.body.classList.contains('view-graph')" in PANEL_HTML
    assert "if (!force && !isGraphViewActive())" in update_fn
    assert "graphRenderDirty = true;" in update_fn
    assert "graph.update(selectedGraphData());" in update_fn
    assert "updateGraph({ force: true });" in activate_view


def test_panel_graph_performance_avoids_full_force_on_every_update():
    graph_renderer = PANEL_HTML.split("const graph = (() => {", 1)[1].split(
        "function isGraphViewActive()", 1
    )[0]
    update_body = PANEL_HTML.split("function update(payload)", 1)[1].split(
        "function reset()", 1
    )[0]
    node_circle_css = PANEL_HTML.split(".graph-node circle {", 1)[1].split("}", 1)[0]

    assert "contextFrameTick" not in graph_renderer
    assert "updateContextFrameBounds" not in graph_renderer
    assert "const structureChanged =" in update_body
    assert "simulation.alpha(1);" in update_body
    assert "for (let i = 0; i < 300; i++) simulation.tick();" in update_body
    assert "simulation.alpha(0);" in update_body
    assert "simulation.alpha(Math.max(simulation.alpha(), 0.06)).restart();" in update_body
    assert "simulation.alpha(0.6).restart();" not in PANEL_HTML
    assert "filter: drop-shadow" not in node_circle_css

def test_panel_graph_clears_stale_root_flag_when_reusing_nodes():
    graph_renderer = GRAPH_JS

    assert "function normalizeGraphNode(src)" in graph_renderer
    assert "isRoot: false," in graph_renderer
    assert "return Object.assign(prev || {}, normalizeGraphNode(src));" in graph_renderer
    assert "return Object.assign(prev || {}, src);" not in graph_renderer


def test_panel_resizers_use_short_rounded_rect_handles():
    resizer_css = PANEL_HTML.split(".resizer::before {", 1)[1].split("}", 1)[0]
    resizer_hover_css = PANEL_HTML.split("body.resizing .resizer.active::before {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: var(--left-aside-w) 8px minmax(0, 1fr) 8px var(--right-aside-w);" in PANEL_HTML
    assert 'id="left-resizer" class="resizer"' in PANEL_HTML
    assert 'id="right-resizer" class="resizer"' in PANEL_HTML
    assert "left: 50%;" in resizer_css
    assert "top: 50%;" in resizer_css
    assert "width: 4px;" in resizer_css
    assert "height: 44px;" in resizer_css
    assert "transform: translate(-50%, -50%);" in resizer_css
    assert "bottom: 14px;" not in resizer_css
    assert "height: 56px;" in resizer_hover_css
    assert "var(--primary)" not in resizer_hover_css


def test_panel_sidebar_itself_is_viewport_constrained_and_scrollable():
    sidebar_css = PANEL_HTML.split("aside.side-panel {", 1)[1].split("}", 1)[0]
    sheet_body_css = PANEL_HTML.split(".sheet-body {", 1)[1].split("}", 1)[0]
    side_section_css = PANEL_HTML.split("details.side-section {", 1)[1].split("}", 1)[0]
    side_scroll_css = PANEL_HTML.split("details.side-scroll-section[open] {", 1)[1].split("}", 1)[0]
    task_section_css = PANEL_HTML.split("details.side-task-section[open] {", 1)[1].split("}", 1)[0]

    # The sidebar shares the top app bar, so only the body row scrolls under it.
    assert "display: grid;" in sidebar_css
    assert "grid-template-rows: minmax(0, 1fr);" in sidebar_css
    assert "height: 100dvh;" not in sidebar_css
    assert "max-height: 100dvh;" not in sidebar_css
    assert "align-self: stretch;" in sidebar_css
    assert "border-radius: var(--tds-radius-xl);" in sidebar_css
    assert "border-radius: var(--md-sys-shape-corner-lg) 0 0 var(--md-sys-shape-corner-lg);" not in sidebar_css
    assert 'class="sheet-header"' not in PANEL_HTML
    assert 'id="side-title"' not in PANEL_HTML
    # The scrollable region is the sheet-body, not the aside itself.
    assert "overflow-y: auto;" in sheet_body_css
    assert "overscroll-behavior: contain;" in sheet_body_css
    assert "scrollbar-gutter: stable both-edges;" in sheet_body_css
    assert "overflow: visible;" in side_section_css
    assert "display: grid;" in PANEL_HTML.split("details.side-section[open] {", 1)[1].split("}", 1)[0]
    assert "grid-template-rows: auto minmax(0, auto);" in PANEL_HTML
    assert "max-height: none;" in task_section_css


def test_panel_sidebar_long_content_uses_flow_safe_grid_items():
    side_section_css = PANEL_HTML.split("details.side-section {", 1)[1].split("}", 1)[0]
    side_body_css = PANEL_HTML.split(".side-body {", 1)[1].split("}", 1)[0]
    side_plan_css = PANEL_HTML.split("#side-plan {", 1)[1].split("}", 1)[0]
    todo_css = PANEL_HTML.split(".todo {", 1)[1].split("}", 1)[0]
    action_summary_css = PANEL_HTML.split(".action-summary-card .summary-head {", 1)[1].split("}", 1)[0]

    assert "position: relative;" in side_section_css
    assert "flex: 0 0 auto;" in side_section_css
    assert "width: 100%;" in side_section_css
    assert "min-width: 0;" in side_body_css
    assert "max-width: 100%;" in side_body_css
    assert "word-break: break-word;" in side_body_css
    assert "display: grid;" in side_plan_css
    assert "grid-auto-rows: minmax(28px, auto);" in side_plan_css
    assert "row-gap: 6px;" in side_plan_css
    assert "grid-template-columns: 30px minmax(0, 1fr);" in todo_css
    assert "box-sizing: border-box;" in todo_css
    assert "height: auto;" in todo_css
    assert "min-height: 28px;" in todo_css
    assert "margin: 0;" in todo_css
    assert "white-space: normal;" in todo_css
    assert "display: flex;" in action_summary_css
    assert "align-items: flex-start;" in action_summary_css
    assert ".todo .text  { color: var(--fg); min-width: 0; overflow-wrap: anywhere; }" in PANEL_HTML
    assert "min-width: 0;" in PANEL_HTML.split(".action-summary-card .summary-copy {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: anywhere;" in PANEL_HTML.split(".action-summary-card .summary-copy {", 1)[1].split("}", 1)[0]


def test_panel_sidebar_toggle_uses_google_material_drop_down_icon():
    toggle_css = PANEL_HTML.split("details.side-section > summary::after {", 1)[1].split("}", 1)[0]
    open_toggle_css = PANEL_HTML.split("details.side-section[open] > summary::after {", 1)[1].split("}", 1)[0]

    assert 'content: "";' in toggle_css
    assert "--section-toggle-icon-url:" in toggle_css
    assert "viewBox='0 -960 960 960'" in toggle_css
    assert "M480-360 280-560h400L480-360Z" in toggle_css
    assert "background-color: currentColor;" in toggle_css
    assert "-webkit-mask: var(--section-toggle-icon-url) center / 24px 24px no-repeat;" in toggle_css
    assert "mask: var(--section-toggle-icon-url) center / 24px 24px no-repeat;" in toggle_css
    assert "border-right:" not in toggle_css
    assert "border-bottom:" not in toggle_css
    assert "transform: rotate(-90deg);" in toggle_css
    assert "transform: rotate(0deg);" in open_toggle_css
    assert "linear-gradient(45deg" not in toggle_css


def test_panel_sidebar_sections_use_toss_masked_section_icons():
    before_css = PANEL_HTML.split("details.side-section > summary::before {", 1)[1].split("}", 1)[0]

    assert 'content: "";' in before_css
    assert "background-color: currentColor;" in before_css
    assert "-webkit-mask: var(--section-icon-url) center / 20px 20px no-repeat;" in before_css
    assert "mask: var(--section-icon-url) center / 20px 20px no-repeat;" in before_css
    for icon in [
        "task_alt",
        "monitor_heart",
        "route",
        "play_circle",
        "ads_click",
        "psychology",
        "account_tree",
    ]:
        assert f'details.side-section > summary[data-icon="{icon}"]::before' in PANEL_HTML
    assert '<summary data-icon="task_alt">Task</summary>' in PANEL_HTML
    assert '<summary data-icon="monitor_heart">Status</summary>' in PANEL_HTML
    assert '<summary data-icon="route">Plan</summary>' in PANEL_HTML
    assert '<summary data-icon="history">Activity</summary>' not in PANEL_HTML


def test_panel_empty_state_uses_toss_neutral_asset_slot():
    empty_icon_css = PANEL_HTML.split("#empty-state::before {", 1)[1].split("}", 1)[0]

    assert 'content: "";' in empty_icon_css
    assert "background: var(--tds-blue-50);" in empty_icon_css
    assert "border-radius: var(--tds-radius-3xl);" in empty_icon_css


def test_panel_step_complete_does_not_render_extra_timeline_summary():
    step_complete_case = PANEL_HTML.split("case 'step_complete':", 1)[1].split(
        "case 'task_complete':", 1
    )[0]
    summary_css = PANEL_HTML.split(".action-summary-card {", 1)[1].split("}", 1)[0]
    summary_hover_css = PANEL_HTML.split(".action-summary-card:hover {", 1)[1].split("}", 1)[0]

    assert "addBlock('plain'," not in step_complete_case
    assert "step complete" not in step_complete_case
    assert "addBlock('green'," not in step_complete_case
    assert "border-left" not in summary_css
    assert "--phase-border" not in summary_css
    assert "--phase-bg" not in summary_css
    assert "--phase-bg" not in summary_hover_css


def test_panel_step_complete_removes_non_action_summary_cards():
    step_complete_case = PANEL_HTML.split("case 'step_complete':", 1)[1].split(
        "case 'task_complete':", 1
    )[0]
    remove_helper = PANEL_HTML.split("function removeNonActionStep(stepId)", 1)[1].split(
        "\nfunction ", 1
    )[0]

    assert "function removeNonActionStep(stepId)" in PANEL_HTML
    assert "const key = stepKey(stepId);" in remove_helper
    assert "const card = actionSummaryCardsByStep.get(key);" in remove_helper
    assert "if (card) card.remove();" in remove_helper
    assert "actionSummaryCardsByStep.delete(key);" in remove_helper
    assert "actionSummariesByStep.delete(key);" in remove_helper
    assert "reasoningByStep.delete(key);" in remove_helper
    assert "timelineStepGroupHasMeaningfulChildren(group)" in remove_helper
    assert "!child.classList.contains('action-summary-card')" in PANEL_HTML
    assert "const actions = actionExecutionsByStep.get(key);" in step_complete_case
    assert "if (!actions || !actions.length) removeNonActionStep(ev.step_id);" in step_complete_case


def test_panel_non_action_cleanup_preserves_final_message_and_error_blocks():
    step_error_case = PANEL_HTML.split("case 'step_error':", 1)[1].split(
        "case 'model_request_retry':", 1
    )[0]
    task_complete_case = PANEL_HTML.split("case 'task_complete':", 1)[1].split(
        "case 'task_failed':", 1
    )[0]

    assert "recordStepError(ev.step_id, ev.error_message);" in step_error_case
    assert "addBlock('red', `<div class=\"title\">error</div><div class=\"meta\">${escHtml(ev.error_message || 'unknown error')}</div>`);" in step_error_case
    assert "finishActionStepGroup(ev.step_id);" in step_error_case
    assert "const finalMessage = pendingAgentFinalMessage || ev.final_reasoning || ev.summary;" in task_complete_case
    assert "if (finalMessage) addRow('agent-message', renderMarkdownSafe(finalMessage));" in task_complete_case


def test_panel_task_complete_renders_browser_agent_speech_bubble():
    review_case = PANEL_HTML.split("case 'review_metadata_extracted':", 1)[1].split(
        "case 'action_executed':", 1
    )[0]
    step_complete_case = PANEL_HTML.split("case 'step_complete':", 1)[1].split(
        "case 'task_complete':", 1
    )[0]
    task_complete_case = PANEL_HTML.split("case 'task_complete':", 1)[1].split(
        "case 'task_failed':", 1
    )[0]
    agent_message_css = PANEL_HTML.split(".row.agent-message {", 1)[1].split("}", 1)[0]

    assert "if (ev.final_result_summary) pendingAgentFinalMessage = ev.final_result_summary;" in review_case
    assert "if (!pendingAgentFinalMessage && ev.final_reasoning) pendingAgentFinalMessage = ev.final_reasoning;" in step_complete_case
    assert "const finalMessage = pendingAgentFinalMessage || ev.final_reasoning || ev.summary;" in task_complete_case
    assert "if (finalMessage) addRow('agent-message', renderMarkdownSafe(finalMessage));" in task_complete_case
    assert "pendingAgentFinalMessage = null;" in task_complete_case
    assert "addBlock('green'," not in task_complete_case
    assert "task complete" not in task_complete_case
    assert "align-self: flex-start;" in agent_message_css
    assert "text-align: left;" in agent_message_css
    assert "background: var(--md-sys-color-secondary-container);" in agent_message_css
    assert "color: var(--md-sys-color-on-secondary-container);" in agent_message_css
    assert "surface-container" not in agent_message_css


def test_panel_task_failed_renders_browser_agent_error_speech_bubble():
    task_failed_case = PANEL_HTML.split("case 'task_failed':", 1)[1].split(
        "case 'task_interrupted':", 1
    )[0]
    failed_message_css = PANEL_HTML.split(".row.agent-message.failed-message {", 1)[1].split("}", 1)[0]
    message_meta_css = PANEL_HTML.split(".row.agent-message .message-meta {", 1)[1].split("}", 1)[0]

    assert "const errorMessage = ev.error_message || 'unknown error';" in task_failed_case
    assert "addRow('agent-message failed-message'," in task_failed_case
    assert '<div class="message-title">task failed</div>' in task_failed_case
    assert '<div class="message-meta">${renderMarkdownSafe(errorMessage)}</div>' in task_failed_case
    assert "addBlock('red'," not in task_failed_case
    assert "background: var(--md-sys-color-error-container);" in failed_message_css
    assert "color: var(--md-sys-color-on-error-container);" in failed_message_css
    assert "color: inherit;" in message_meta_css


def test_panel_agent_messages_use_safe_markdown_renderer():
    markdown_css = PANEL_HTML.split(".row.agent-message .message-markdown {", 1)[1].split("}", 1)[0]

    assert "function renderMarkdownSafe(markdown)" in PANEL_HTML
    assert "function renderInlineMarkdown(rawText)" in PANEL_HTML
    assert "function safeMarkdownHref(url)" in PANEL_HTML
    assert "escHtml(fenceLines.join('\\n'))" in PANEL_HTML
    assert "target=\"_blank\" rel=\"noreferrer\"" in PANEL_HTML
    assert "/^(https?:|mailto:)/i.test(trimmed)" in PANEL_HTML
    assert "/^\\/(?!\\/)/.test(trimmed) || /^#/.test(trimmed)" in PANEL_HTML
    assert "overflow-wrap: anywhere;" in markdown_css


def test_panel_action_summaries_render_clickable_timeline_cards_without_inline_details():
    review_case = PANEL_HTML.split("case 'review_metadata_extracted':", 1)[1].split(
        "case 'action_executed':", 1
    )[0]

    assert "function upsertActionSummary(item)" in PANEL_HTML
    assert "function renderActionSummaryCard(card, item)" in PANEL_HTML
    assert "currentTimelineStepGroup.appendChild(card);" in PANEL_HTML
    assert "upsertActionSummary({" in review_case
    assert "addActivity({" not in review_case
    assert '<div role="button" tabindex="0" class="action-summary-card"' in PANEL_HTML
    assert "selectTimelineActionStep(key);" in PANEL_HTML
    assert "Action summary details" not in PANEL_HTML


def test_panel_right_additional_info_includes_reasoning_artifacts_and_llm_button():
    assert "let reasoningByStep = new Map();" in PANEL_HTML
    assert "storeStepReasoning(ev.step_id, ev.reasoning);" in PANEL_HTML
    assert "refreshAdditionalInfoForStep(stepId);" in PANEL_HTML
    assert "function renderActionStepAdditionalInfo(stepId)" in PANEL_HTML
    assert "function renderTimelineActionStepInfo(stepId)" in PANEL_HTML
    assert "return renderActionStepAdditionalInfo(stepId);" in PANEL_HTML
    for label in (
        "Action step number",
        "Summary",
        "Outcome",
        "Reasoning",
        "Function call",
        "Function call arguments",
    ):
        assert label in PANEL_HTML
    assert "Reasoning" in PANEL_HTML
    step_render = PANEL_HTML.split("function renderActionStepAdditionalInfo(stepId)", 1)[1].split(
        "function renderTimelineActionStepInfo", 1
    )[0]
    assert "renderActionArtifacts(artifacts, actionContext)" in step_render
    assert "renderRightPanelAuxiliarySections(inference, artifacts, actionNode)" in step_render
    assert "let artifactsByStep = new Map();" in PANEL_HTML
    assert "storeArtifactsForStep(ev.step_id, ev.artifacts);" in PANEL_HTML


def test_panel_agent_step_raw_events_are_hidden_behind_action_summary_details():
    reasoning_case = PANEL_HTML.split("case 'reasoning_extracted':", 1)[1].split(
        "case 'function_calls_extracted':", 1
    )[0]
    calls_case = PANEL_HTML.split("case 'function_calls_extracted':", 1)[1].split(
        "case 'review_metadata_extracted':", 1
    )[0]
    action_case = PANEL_HTML.split("case 'action_executed':", 1)[1].split(
        "case 'step_error':", 1
    )[0]

    assert "addRow('thinking'" not in reasoning_case
    assert "storeFunctionCalls(ev.step_id, calls);" in calls_case
    assert "addRow('', `<span style=\"color:var(--fg-dim)\">⚙" not in calls_case
    assert "storeObservedUrl(ev.step_id, ev.env_state.url);" in action_case
    assert "addRow('dim', `@ <span class=\"url\">" not in action_case
    assert "Function call" in PANEL_HTML
    assert "Function call arguments" in PANEL_HTML


def test_panel_user_chat_message_bubble_keeps_right_edge_but_text_is_left_aligned():
    task_started_case = PANEL_HTML.split("case 'task_started':", 1)[1].split(
        "case 'planner_started':", 1
    )[0]
    step_started_case = PANEL_HTML.split("case 'step_started':", 1)[1].split(
        "case 'llm_inference':", 1
    )[0]

    assert "addSpeaker('user', null);" in task_started_case
    assert "addRow('user-message', escHtml(ev.query));" in task_started_case
    assert "addSpeaker('browser-agent', null);" in task_started_case
    assert "addSpeaker('browser-agent', `step ${ev.step_id}`);" not in step_started_case
    assert "addSpeaker('browser-agent'" not in step_started_case
    assert "el.className = `speaker ${name === 'user' ? 'user-speaker' : 'agent-speaker'}`;" in PANEL_HTML
    assert ".row.user-message" in PANEL_HTML
    user_message_css = PANEL_HTML.split(".row.user-message {", 1)[1].split("}", 1)[0]
    assert "align-self: flex-end;" in user_message_css
    assert "text-align: left;" in user_message_css
    assert "text-align: right;" not in user_message_css
    assert ".speaker.user-speaker" in PANEL_HTML


def test_panel_removes_keybind_help_bar():
    assert 'class="keybind"' not in PANEL_HTML
    assert "enter</kbd> submit" not in PANEL_HTML
    assert "shift+enter</kbd> newline" not in PANEL_HTML
    assert "esc</kbd> interrupt" not in PANEL_HTML
    assert '"keybind resizer aside"' not in PANEL_HTML
    assert '"header       header       header  header        header"' in PANEL_HTML
    assert 'grid-template-areas: "header" "main" "footer";' in PANEL_HTML


def test_panel_graph_selection_renders_action_before_after_artifacts():
    assert "function renderActionArtifacts(artifacts" in PANEL_HTML
    assert "function replayArtifactHref(path, expectedDir = 'history')" in PANEL_HTML
    assert "beforeScreenshotPath: ev.artifacts && ev.artifacts.before_screenshot_path" in PANEL_HTML
    assert "afterScreenshotPath: ev.artifacts && (ev.artifacts.after_screenshot_path || ev.artifacts.screenshot_path)" in PANEL_HTML
    assert "actionVideoPath: ev.artifacts && ev.artifacts.action_video_path" in PANEL_HTML
    assert "actionGifPath: ev.artifacts && (ev.artifacts.action_clip_gif_path || ev.artifacts.action_gif_path)" in PANEL_HTML
    assert "videoPath: ev.artifacts && ev.artifacts.video_path" in PANEL_HTML
    assert "renderActionReplayVideoCard('Action replay', actionVideo)" in PANEL_HTML
    assert "!actionVideo ? renderActionReplayCard('Action replay', actionClip) : ''" in PANEL_HTML
    assert "renderBeforeAfterCompare(beforeShot, afterShot)" in PANEL_HTML
    assert "renderArtifactCard('session video', video, 'video')" in PANEL_HTML
    assert "renderActionArtifacts(d.artifacts, d)" in PANEL_HTML


def test_panel_graph_action_nodes_use_step_detail_or_group_info_by_step_count():
    graph_selection = PANEL_HTML.split("function renderSelection(d)", 1)[1].split(
        "function setGraphDrilldown", 1
    )[0]
    graph_node_selection = PANEL_HTML.split("function renderGraphNodeSelection(d)", 1)[1].split(
        "function renderSelection", 1
    )[0]

    assert "function renderGraphNodeSelection(d)" in PANEL_HTML
    assert "if (d.type === 'action')" in graph_selection
    assert "renderActionGroupAdditionalInfo(d);" in graph_selection
    assert "renderActionStepAdditionalInfo(stepIds[0]);" not in graph_selection
    assert "renderGraphNodeSelection(d);" in graph_selection
    assert "renderActionArtifacts(d.artifacts, d)" in graph_node_selection
    assert "renderActionPreviewGallery(d.actionPreviews)" in graph_node_selection


def test_panel_graph_and_timeline_selection_share_action_step_highlight_and_info():
    assert ".action-step-group.timeline-highlight" in PANEL_HTML
    assert "function beginActionStepGroup(stepId)" in PANEL_HTML
    assert "currentTimelineStepGroup.dataset.stepId = String(stepId);" in PANEL_HTML
    assert "currentTimelineStepGroup.addEventListener('click'" in PANEL_HTML
    assert "function selectTimelineActionStep(stepId)" in PANEL_HTML
    assert "selectGraphActionForStep(key);" in PANEL_HTML
    assert "renderActionStepAdditionalInfo(selectedTimelineStepId);" in PANEL_HTML
    assert "function highlightTimelineActionStep(stepId)" in PANEL_HTML
    assert "function timelineStepForGraphNode(d)" in PANEL_HTML
    assert "highlightTimelineActionStep(timelineStepForGraphNode(selectedNodeData));" in PANEL_HTML
    assert "highlightTimelineActionStep(null);" in PANEL_HTML
    assert "appendTimelineElement(el);" in PANEL_HTML
    assert "if (currentTimelineStepGroup) currentTimelineStepGroup.appendChild(el);" in PANEL_HTML


def test_panel_graph_edges_are_selectable_and_sync_evidence_panel():
    assert "let selectedEdgeKey = null;" in GRAPH_JS
    assert "let selectedEdgeData = null;" in GRAPH_JS
    assert "function graphEdgeKey(edge)" in GRAPH_JS
    assert "function selectGraphEdge(d)" in GRAPH_JS
    assert "selectedEdgeKey = graphEdgeKey(d);" in GRAPH_JS
    assert "renderGraphEdgeSelection(selectedEdgeData);" in GRAPH_JS
    assert "function renderGraphEdgeSelection(edge)" in GRAPH_JS
    assert "renderEdgeReplayArtifacts(edge)" in GRAPH_JS
    assert "renderRightPanelAuxiliarySections(anchorNode && anchorNode.llmInference, anchorNode && anchorNode.artifacts);" in GRAPH_JS

    graph_renderer = GRAPH_JS.split("linkSel = linkG.selectAll('path.graph-link')", 1)[1].split(
        "nodeSel = nodeG.selectAll('g.graph-node')", 1
    )[0]
    assert ".on('click', (event, d) => { event.stopPropagation(); selectGraphEdge(d); })" in graph_renderer
    assert ".classed('selected', d => graphEdgeKey(d) === selectedEdgeKey)" in graph_renderer
    assert "linksData = incomingLinks.map(e => ({ ...e, mode: payload.mode }));" in GRAPH_JS

    assert "linkG.selectAll('path.graph-link').classed('selected', d => graphEdgeKey(d) === selectedEdgeKey);" in GRAPH_JS
    assert ".graph-link.selected" in PANEL_CSS


def test_panel_selected_graph_edge_changes_stroke_color_without_outline_effects():
    selected_edge_rule = re.search(r"\.graph-link\.selected\s*\{([^}]*)\}", PANEL_CSS)

    assert selected_edge_rule is not None
    assert "stroke: var(--graph-accent-selected);" in selected_edge_rule.group(1)
    assert "stroke-width:" not in selected_edge_rule.group(1)
    assert "filter:" not in selected_edge_rule.group(1)


def test_panel_select_graph_action_for_step_drills_to_action_layer_and_selects_node():
    selector = PANEL_HTML.split("function selectGraphActionForStep(stepId)", 1)[1].split(
        "function updateGraphSelectionClass", 1
    )[0]

    assert "backendActionNodeForStep(key)" not in selector
    assert "const actionId = actionNodeIdByStep.get(key);" in selector
    assert "const actionNode = actionId ? trajectoryActions.get(actionId) : null;" in selector
    assert "graphDrilldown = { level: 'action', urlId: actionNode.urlId, viewportId: actionNode.viewportId };" in selector
    assert "selectedNodeId = actionNode.id;" in selector
    assert "selectedNodeData = actionNode;" in selector
    assert "updateGraph();" in selector


def test_action_nodes_can_be_selected_by_timeline_step_from_client_graph():
    assert "function backendActionNodeForStep(stepId)" not in GRAPH_JS
    action_lookup = GRAPH_JS.split("function actionNodeForStep(stepId)", 1)[1].split(
        "\nasync function ", 1
    )[0]
    assert "backendActionNodeForStep(stepId)" not in action_lookup
    assert "const actionId = actionNodeIdByStep.get(String(stepId));" in action_lookup
    assert "return actionId ? trajectoryActions.get(actionId) : null;" in action_lookup


def test_panel_action_group_info_lists_members_and_links_to_single_step_detail():
    assert "function renderActionGroupAdditionalInfo(actionNode)" in PANEL_HTML
    group_render = PANEL_HTML.split("function renderActionGroupAdditionalInfo(actionNode)", 1)[1].split(
        "window.renderActionGroupAdditionalInfo", 1
    )[0]

    for label in (
        "Action steps",
        "Summary",
        "Outcome",
        "Reasoning",
        "Function call",
        "Function call arguments",
    ):
        assert label in group_render
    assert "related action steps" in group_render
    assert "data-action-member-step" in group_render
    assert "selectTimelineActionStep(stepId);" in group_render


def test_panel_graph_separates_selected_and_running_node_accents():
    assert "let activeGraphStepId = null;" in PANEL_HTML
    assert "let trajectoryCurrentViewportId = null;" in PANEL_HTML
    assert "let trajectoryCurrentActionId = null;" in PANEL_HTML
    assert "function isRunningGraphNode(d)" in PANEL_HTML
    assert ".graph-node.selected circle" in PANEL_HTML
    assert ".graph-node.current circle" in PANEL_HTML
    assert ".graph-node.running circle" in PANEL_HTML
    assert "trajectoryCurrentViewportId = viewportId;" in PANEL_HTML
    assert "trajectoryCurrentActionId = actionId;" in PANEL_HTML
    assert "isCurrent: vp.id === trajectoryCurrentViewportId" in PANEL_HTML
    assert "isCurrent: action.id === trajectoryCurrentActionId" in PANEL_HTML
    assert ".classed('current', d => !!d.isCurrent)" in PANEL_HTML
    assert ".classed('running', d => isRunningGraphNode(d))" in PANEL_HTML
    assert ".classed('selected', d => d.id === selectedNodeId)" in PANEL_HTML
    assert ".classed('current', d => d.isCurrent)" not in PANEL_HTML
    assert "activeGraphStepId = stepId != null ? String(stepId) : null;" in PANEL_HTML
    assert "function refreshRunning()" in PANEL_HTML
    assert "return { update, reset, resize, refreshSelection, refreshRunning, fitToNodes };" in PANEL_HTML
    assert "updateGraphRunningClass();" in PANEL_HTML


def test_panel_graph_uses_visit_count_for_node_size_and_color_scale():
    assert "fill: var(--graph-node-fill, var(--surface-2));" in PANEL_HTML
    assert "--graph-work-color-low:      #482878;" in PANEL_CSS
    assert "--graph-work-color-low-mid:  #3e4989;" in PANEL_CSS
    assert "--graph-work-color-mid:      #26828e;" in PANEL_CSS
    assert "--graph-work-color-high-mid: #35b779;" in PANEL_CSS
    assert "--graph-work-color-high:     #fde725;" in PANEL_CSS
    work_color_vars = PANEL_CSS.split("--graph-work-color-low:", 1)[1].split("--shadow:", 1)[0]
    assert "var(--tds-" not in work_color_vars
    # actionStepCount still powers the "total steps" tooltip row, but no longer
    # drives node size/color.
    assert "function actionStepCountForActionIds(actionIds)" in PANEL_HTML
    assert "actionStepCount: actionStepCountForActionIds(src.actionIds)" in PANEL_HTML
    assert "actionStepCount: actionStepCountForActionIds(vp.actionIds)" in PANEL_HTML
    assert "actionStepCount: actionStepCountForAction(action)" in PANEL_HTML
    # Repeated node highlight encodes visit count. Size/color reuse the cue
    # layer's nodeVisitCount so the magnitude and the `repeated` cue agree.
    assert "function graphNodeVisitCount(d)" in PANEL_HTML
    visit_count = PANEL_HTML.split("function graphNodeVisitCount(d)", 1)[1].split(
        "function trajectoryMaxVisitCount", 1
    )[0]
    assert "return nodeVisitCount(d.type, d);" in visit_count
    assert "function trajectoryMaxVisitCount()" in PANEL_HTML
    radius = PANEL_HTML.split("function graphNodeRadius(d)", 1)[1].split("\n  function ", 1)[0]
    assert "graphNodeVisitCount(d)" in radius
    assert "function graphWorkColor(t)" in PANEL_HTML
    assert "var(--graph-work-color-low-mid)" in PANEL_HTML
    assert "var(--graph-work-color-high-mid)" in PANEL_HTML
    assert "function graphNodeFill(d, maxVisitCount)" in PANEL_HTML
    assert "const minVisitCount = 1;" in PANEL_HTML
    assert "const clampedMaxVisitCount = Math.max(minVisitCount, maxVisitCount);" in PANEL_HTML
    assert "const clampedCount = Math.max(minVisitCount, Math.min(count, clampedMaxVisitCount));" in PANEL_HTML
    assert "const normalized = Math.sqrt((clampedCount - minVisitCount) / Math.max(1, clampedMaxVisitCount - minVisitCount));" in PANEL_HTML
    assert "return graphWorkColor(normalized);" in PANEL_HTML
    assert "const maxVisitCount = Math.max(1, trajectoryMaxVisitCount(), ...nodesData.map(graphNodeVisitCount));" in PANEL_HTML
    assert ".style('--graph-node-fill', d => graphNodeFill(d, maxVisitCount));" in PANEL_HTML
    assert "stroke: transparent;" in PANEL_HTML
    assert "stroke-width: 0;" in PANEL_HTML


def test_panel_current_node_accent_preserves_work_fill():
    current_rule = PANEL_HTML.split(".graph-node.current circle {", 1)[1].split("}", 1)[0]
    assert "stroke: var(--graph-accent-current);" in current_rule
    assert "stroke-width: 3;" in current_rule
    assert "fill:" not in current_rule
    assert "filter:" not in current_rule


def test_panel_graph_base_nodes_hide_stroke_until_accented():
    base_rule = PANEL_HTML.split(".graph-node circle {", 1)[1].split("}", 1)[0]
    assert "stroke: transparent;" in base_rule
    assert "stroke-width: 0;" in base_rule
    assert "stroke-width 0.16s ease" in base_rule
    assert ".graph-node.root circle" in PANEL_HTML
    assert ".graph-node.url circle" in PANEL_HTML
    assert ".graph-node.viewport circle" in PANEL_HTML
    assert ".graph-node.action circle" in PANEL_HTML
    for accent in (".graph-node.current circle", ".graph-node.running circle", ".graph-node.selected circle"):
        rule = PANEL_HTML.split(accent + " {", 1)[1].split("}", 1)[0]
        assert "stroke:" in rule
        assert "stroke-width: 3;" in rule
        assert "fill:" not in rule
        assert "filter:" not in rule


def test_panel_graph_endpoint_shapes_use_default_shape_stroke_without_cue_shape():
    endpoint_shape_rule = re.search(
        r"\.graph-node\.start \.graph-node-shape,\n  \.graph-node\.end \.graph-node-shape \{([^}]*)\}",
        PANEL_CSS,
    )
    assert endpoint_shape_rule
    assert "stroke: transparent;" in endpoint_shape_rule.group(1)
    assert "stroke-width: 0;" in endpoint_shape_rule.group(1)
    assert ".graph-node.root.start .graph-node-shape" not in PANEL_CSS
    assert ".graph-node.root.end .graph-node-shape" not in PANEL_CSS

    assert ".graph-node.start > circle,\n  .graph-node.end > circle { display: none; }" in PANEL_CSS

    assert "enter.append('path').attr('class', 'graph-node-cue-shape');" in GRAPH_JS
    ring_body = GRAPH_JS.split("nodeSel.select('circle.cue-ring').each(function(d)", 1)[1].split(
        "nodeSel.select('path.graph-node-cue-shape')", 1
    )[0]
    assert "const isEndpoint = !!(d.isStart || d.isEnd);" not in ring_body
    assert "cueType ? null : 'none'" in ring_body

    cue_shape_body = GRAPH_JS.split("nodeSel.select('path.graph-node-cue-shape').each(function(d)", 1)[1].split(
        "nodeSel.select('path.graph-node-shape')", 1
    )[0]
    assert "const isEndpoint = !!(d.isStart || d.isEnd);" in cue_shape_body
    assert "const cueType = ownCueRingType(d);" in cue_shape_body
    assert "cueType && isEndpoint" in cue_shape_body
    assert "`graph-node-cue-shape cue-${cueType}`" in cue_shape_body
    assert ".style('display', cueType && isEndpoint ? null : 'none')" in cue_shape_body

    shape_body = GRAPH_JS.split("nodeSel.select('path.graph-node-shape')", 1)[1].split(
        "nodeSel.select('text.graph-node-label')", 1
    )[0]
    assert "cue-${cueType}" not in shape_body


def test_panel_graph_shows_work_color_legend():
    assert 'id="graph-legend"' in PANEL_HTML
    assert 'aria-label="Node color legend"' in PANEL_HTML
    assert '<div class="legend-title">visit count</div>' in PANEL_HTML
    assert "data-legend-max" in PANEL_HTML
    assert "<span>0</span>" not in PANEL_HTML_ONLY
    assert "<span>1</span>" in PANEL_HTML_ONLY
    assert "<span data-legend-max>1</span>" in PANEL_HTML
    graph_wrap_css = PANEL_HTML.split("#graph-wrap {", 1)[1].split("}", 1)[0]
    assert "--graph-overlay-legend-width: 144px;" in graph_wrap_css
    legend_css = PANEL_HTML.split(".graph-legend {", 1)[1].split(".graph-legend.hidden", 1)[0]
    assert "top:" not in legend_css
    assert "right: 14px;" in legend_css
    assert "bottom: 104px;" in legend_css
    assert "width: var(--graph-overlay-legend-width);" in legend_css
    cue_legend_css = PANEL_HTML.split(".graph-cue-legend {", 1)[1].split("}", 1)[0]
    assert "width: var(--graph-overlay-legend-width);" in cue_legend_css
    scale_css = PANEL_HTML.split(".graph-legend .legend-scale {", 1)[1].split("}", 1)[0]
    assert "flex-direction: column;" in scale_css
    bar_css = PANEL_HTML.split(".graph-legend .legend-bar {", 1)[1].split("}", 1)[0]
    assert "width: 100%;" in bar_css
    assert "height: 10px;" in bar_css
    assert "background: linear-gradient(90deg, var(--graph-work-color-low) 0%, var(--graph-work-color-low-mid) 25%, var(--graph-work-color-mid) 50%, var(--graph-work-color-high-mid) 75%, var(--graph-work-color-high) 100%);" in bar_css
    labels_css = PANEL_HTML.split(".graph-legend .legend-labels {", 1)[1].split("}", 1)[0]
    assert "flex-direction: row;" in labels_css
    assert "justify-content: space-between;" in labels_css
    assert "column-reverse" not in labels_css
    assert "const legendEl = document.getElementById('graph-legend');" in PANEL_HTML
    assert "function updateGraphLegend(maxVisitCount, hasNodes)" in PANEL_HTML
    assert "const legendMinVisitCount = 1;" in PANEL_HTML
    assert "const roundedMaxVisitCount = Math.max(legendMinVisitCount, Math.round(Number(maxVisitCount) || 0));" in PANEL_HTML
    assert "maxLabel.textContent = `${roundedMaxVisitCount}`;" in PANEL_HTML
    assert "updateGraphLegend(maxVisitCount, nodesData.length > 0);" in PANEL_HTML
    assert "updateGraphLegend(1, false);" in PANEL_HTML


def test_panel_graph_hover_tooltip_stays_compact():
    tooltip_block = GRAPH_JS.split("function graphTooltipHtml(d) {", 1)[1].split("function positionGraphTooltip", 1)[0]
    assert "const title = d.label || d.host || d.actionName || d.id;" in tooltip_block
    assert "<span>level</span>" in tooltip_block
    assert "<span>total steps</span>" in tooltip_block
    assert "<span>unique actions</span>" in tooltip_block
    assert "<span>visits</span>" in tooltip_block
    assert "drill in" in tooltip_block
    for hidden_detail in ("<span>host</span>", "<span>path</span>", "<span>size</span>", "<span>scroll</span>", "<span>shot</span>", "<span>args</span>", "<span>first step</span>", "<span>last step</span>", "<span>out / in</span>", "<span>click</span>"):
        assert hidden_detail not in tooltip_block


def test_panel_uses_live_session_id_for_graph_artifacts_outside_replay():
    task_started_case = PANEL_HTML.split("case 'task_started':", 1)[1].split(
        "case 'planner_started':", 1
    )[0]
    replay_href = PANEL_HTML.split("function replayArtifactHref(path, expectedDir = 'history')", 1)[1].split(
        "function renderArtifactCard", 1
    )[0]

    assert "let liveSessionId = null;" in PANEL_HTML
    assert "liveSessionId = ev.session_id || null;" in task_started_case
    assert "const sessionId = replayMode ? replaySessionId : liveSessionId;" in replay_href
    assert "if (!sessionId || !path) return '';" in replay_href


def test_panel_aggregates_child_action_gif_previews_for_url_and_viewport_nodes():
    assert "function collectActionPreviewArtifacts(actionIds)" in PANEL_HTML
    assert "artifacts.action_video_path || artifacts.action_clip_gif_path || artifacts.action_gif_path || artifacts.after_screenshot_path || artifacts.screenshot_path" in PANEL_HTML
    assert "artifacts.action_video_path ? 'video' : ((artifacts.action_clip_gif_path || artifacts.action_gif_path) ? 'gif' : 'image')" in PANEL_HTML
    assert "actionPreviews: collectActionPreviewArtifacts(src.actionIds)" in PANEL_HTML
    assert "actionPreviews: collectActionPreviewArtifacts(vp.actionIds)" in PANEL_HTML
    assert "renderActionPreviewGallery(d.actionPreviews)" in PANEL_HTML
    assert "child previews" in PANEL_HTML
    assert ".artifact-gallery" in PANEL_HTML


def test_panel_prefers_action_video_over_gif_fallbacks():
    artifact_renderer = PANEL_HTML.split("function renderActionArtifacts(artifacts", 1)[1].split(
        "function actionPreviewArtifactsFor(action)", 1
    )[0]
    assert "const actionVideo = replayArtifactHref(artifacts.action_video_path, 'history');" in artifact_renderer
    assert "const actionClip = replayArtifactHref(artifacts.action_clip_gif_path, 'history');" in artifact_renderer
    assert "const fallbackActionGif = replayArtifactHref(artifacts.action_gif_path, 'history');" in artifact_renderer
    assert "renderActionReplayVideoCard('Action replay', actionVideo)" in artifact_renderer
    assert "!actionVideo ? renderActionReplayCard('Action replay', actionClip) : ''" in artifact_renderer
    assert "!actionVideo && !actionClip && fallbackActionGif ? renderArtifactCard('Before/after GIF', fallbackActionGif, 'gif') : ''" in artifact_renderer
    assert "action_video_path" in PANEL_HTML
    assert "action_clip_gif_path" in PANEL_HTML


def test_panel_action_replay_media_use_video_and_restartable_image_sources():
    artifact_helpers = PANEL_HTML.split("function replayArtifactHref(path, expectedDir = 'history')", 1)[1].split(
        "function renderBeforeAfterCompare", 1
    )[0]
    action_replay_video_card = PANEL_HTML.split("function renderActionReplayVideoCard(label, href)", 1)[1].split(
        "function renderActionReplayCard", 1
    )[0]
    action_replay_card = PANEL_HTML.split("function renderActionReplayCard(label, href)", 1)[1].split(
        "function renderBeforeAfterCompare", 1
    )[0]

    assert "let animatedArtifactRenderSeq = 0;" in PANEL_HTML
    assert "function animatedArtifactSrc(href)" in artifact_helpers
    assert "animatedArtifactRenderSeq += 1;" in artifact_helpers
    assert "const joiner = href.includes('?') ? '&' : '?';" in artifact_helpers
    assert '<video controls autoplay muted playsinline preload="auto" src="${safeHref}" data-action-replay-video="true"></video>' in action_replay_video_card
    assert "const imgSrc = escHtml(animatedArtifactSrc(href));" in action_replay_card
    assert 'href="${safeHref}"' in action_replay_card
    assert '<img src="${imgSrc}" alt="${safeLabel}" data-action-replay-gif="true">' in action_replay_card


def test_panel_primary_action_replay_media_scales_with_right_panel_width():
    assert ".artifact-primary .artifact-card {" in PANEL_CSS
    assert "width: 100%;" in PANEL_CSS.split(".artifact-primary .artifact-card {", 1)[1].split("}", 1)[0]

    primary_media_css = PANEL_CSS.split(".artifact-primary img,", 1)[1].split("}", 1)[0]
    assert ".artifact-primary video" in primary_media_css
    assert "max-height: none;" in primary_media_css
    assert "height: auto;" in primary_media_css


def test_panel_renders_fallback_and_gallery_gifs_as_animated_artifacts():
    artifact_renderer = PANEL_HTML.split("function renderActionArtifacts(artifacts", 1)[1].split(
        "function actionPreviewArtifactsFor(action)", 1
    )[0]
    gallery_renderer = PANEL_HTML.split("function renderActionPreviewGallery(previews)", 1)[1].split(
        "function llmInferenceForStep", 1
    )[0]

    assert "renderArtifactCard('Before/after GIF', fallbackActionGif, 'gif')" in artifact_renderer
    assert "return renderArtifactCard(label, href, preview.kind);" in gallery_renderer


def test_panel_submit_task_handles_ok_false_and_preserves_input():
    submit_task = PANEL_HTML.split("async function submitTask() {", 1)[1].split("async function interruptTask()", 1)[0]
    assert "const data = await res.json();" in submit_task
    assert "if (!data.ok) throw new Error(data.error || 'Task rejected');" in submit_task
    assert "input.value = '';" not in submit_task.split("try {")[0]
    assert "input.value = '';" in submit_task.split("try {")[1]

def test_panel_interrupt_task_handles_ok_false():
    interrupt_task = PANEL_HTML.split("async function interruptTask() {", 1)[1].split("btn.addEventListener('click'", 1)[0]
    assert "const data = await res.json();" in interrupt_task
    assert "if (!data.ok) throw new Error(data.error || 'Interrupt rejected');" in interrupt_task

def test_panel_stop_button_not_shown_during_is_submitting():
    update_controls = PANEL_HTML.split("function updateControlStates() {", 1)[1].split("}", 1)[0]
    assert "const stopMode = isRunning && !replayMode;" in update_controls
    assert "stopMode = (isRunning || isSubmitting)" not in update_controls


def test_panel_running_state_locks_input_without_dimming_stop_button():
    set_input = PANEL_JS.split("function setInputEnabled(enabled) {", 1)[1].split("function finishTaskUi", 1)[0]

    assert ".input-shell.input-locked" in PANEL_CSS
    assert ".input-shell.composer-disabled" in PANEL_CSS
    assert ".input-shell.disabled" not in PANEL_CSS
    assert "const inputLocked = !enabled && (isRunning || isSubmitting) && !replayMode;" in set_input
    assert "const composerDisabled = !enabled && !inputLocked;" in set_input
    assert "inputShell.classList.toggle('input-locked', inputLocked);" in set_input
    assert "inputShell.classList.toggle('composer-disabled', composerDisabled);" in set_input
    assert "inputShell.classList.toggle('disabled'" not in set_input

def test_panel_replay_mode_processes_live_events_for_state_but_not_ui():
    ws_onmessage = PANEL_HTML.split("ws.onmessage = (e) => {", 1)[1].split("};", 1)[0]
    assert "if (ev.type === 'task_started') liveIsRunning = true;" in ws_onmessage
    assert "if (ev.type === 'task_complete' || ev.type === 'task_failed' || ev.type === 'task_interrupted') liveIsRunning = false;" in ws_onmessage
    assert "if (replayMode) return;" in ws_onmessage
    
    live_btn = PANEL_HTML.split("liveBtn.addEventListener('click', () => {", 1)[1].split("});", 1)[0]
    assert "isRunning = liveIsRunning;" in live_btn


def test_graph_exposes_aria_diff_signature_and_noop_tracking():
    # P1: no-op detection infrastructure (outline §F2 No-op Action Candidate).
    # The action layer must (a) normalize ARIA snapshots, (b) remember the
    # previous post-state, and (c) expose a noopFlag helper that downstream
    # cue computation in P2 can consume.
    assert "function ariaDiffSignature(text)" in GRAPH_JS
    assert "function noopFlag(actionNode)" in GRAPH_JS
    assert "let trajectoryLastSnapshot" in GRAPH_JS
    # Reset wiring so live → replay → live transitions do not leak state.
    reset_body = GRAPH_JS.split("function resetTrajectoryGraphState() {", 1)[1].split("\nfunction ", 1)[0]
    assert "trajectoryLastSnapshot = null;" in reset_body
    # No-op graph cue is evidence-gated; URL/viewport/ARIA snapshot tracking
    # remains as context, but badges wait for DOM+ARIA+screenshot <= K.
    record_body = GRAPH_JS.split("function recordActionExecution(ev)", 1)[1].split("\nfunction ", 1)[0]
    assert "(ev.artifacts && ev.artifacts.aria_snapshot)" in record_body
    assert "postAriaSig = ariaDiffSignature((ev.artifacts && ev.artifacts.aria_snapshot) || '')" in record_body
    assert "noopEvidenceStatus: 'unknown'" in record_body
    assert "primeNoopEvidenceForAction(actionNode)" in record_body
    noop_body = GRAPH_JS.split("function noopFlag(actionNode)", 1)[1].split("\nfunction ", 1)[0]
    assert "noopEvidenceStatus === 'pass'" in noop_body
    assert "trajectoryLastSnapshot = {" in record_body
