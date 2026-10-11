import re
from pathlib import Path

from fastapi.testclient import TestClient

from ui.c2_browser_lens_no_graph.server import app


PANEL_HTML_ONLY = Path("src/ui/c2_browser_lens_no_graph/panel.html").read_text(encoding="utf-8")


def _read_css_bundle(entrypoint: str) -> str:
    path = Path(entrypoint)
    text = path.read_text(encoding="utf-8")
    imports = re.findall(r'@import url\("([^"]+)"\);', text)
    if not imports:
        return text
    return "\n".join((path.parent / imported).read_text(encoding="utf-8") for imported in imports)


PANEL_CSS = _read_css_bundle("src/ui/c2_browser_lens_no_graph/static/panel.css")
GRAPH_ARTIFACTS_JS = Path("src/ui/c2_browser_lens_no_graph/static/graph/graph-artifacts.js").read_text(
    encoding="utf-8"
)
NO_GRAPH_JS = Path("src/ui/c2_browser_lens_no_graph/static/no_graph.js").read_text(encoding="utf-8")
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


def test_no_graph_panel_omits_graph_view():
    assert "<title>BrowserLens</title>" in PANEL_HTML_ONLY
    assert '<span class="title" id="hdr-title">BrowserLens</span>' in PANEL_HTML_ONLY
    assert 'data-view="timeline"' in PANEL_HTML_ONLY
    assert 'data-view="stats"' in PANEL_HTML_ONLY
    assert 'data-view="graph"' not in PANEL_HTML_ONLY
    assert 'id="graph-wrap"' not in PANEL_HTML_ONLY
    assert 'id="graph-svg"' not in PANEL_HTML_ONLY
    assert "d3.v7.min.js" not in PANEL_HTML_ONLY


def test_no_graph_panel_uses_graph_noop_helpers():
    assert '<script src="/static/graph/graph-artifacts.js"></script>' in PANEL_HTML_ONLY
    assert '<script src="/static/graph/graph-right-panel.js"></script>' in PANEL_HTML_ONLY
    assert '<script src="/static/no_graph.js"></script>' in PANEL_HTML_ONLY
    for name in _SHARED_PANEL_JS_PARTS:
        assert f'<script src="/shared-static/panel/{name}"></script>' in PANEL_HTML_ONLY
    assert '<script src="/static/panel.js"></script>' not in PANEL_HTML_ONLY
    assert "graph-render.js" not in PANEL_HTML_ONLY
    assert "graph-build.js" not in PANEL_HTML_ONLY
    assert "function recordActionExecution(_event) {}" in NO_GRAPH_JS
    assert "window.actionNodeForStep = () => null;" in NO_GRAPH_JS


def test_no_graph_panel_history_drawer_markup_is_available():
    assert 'id="sessions-panel" class="hidden sessions-drawer" role="dialog" aria-label="History"' in PANEL_HTML_ONLY
    assert 'aria-modal="false"' in PANEL_HTML_ONLY
    assert 'class="sessions-head-main"' in PANEL_HTML_ONLY
    assert 'class="sessions-title"' in PANEL_HTML_ONLY
    assert 'id="sessions-summary"' in PANEL_HTML_ONLY
    assert 'id="sessions-search"' in PANEL_HTML_ONLY
    assert 'aria-label="Search history"' in PANEL_HTML_ONLY
    assert 'placeholder="Search query, session id, or model"' in PANEL_HTML_ONLY
    assert 'class="sessions-body"' in PANEL_HTML_ONLY
    assert 'id="sessions-list"' in PANEL_HTML_ONLY
    assert 'class="sessions-message"' in PANEL_HTML_ONLY
    assert 'Loading saved sessions' in PANEL_HTML_ONLY
    assert 'aria-label="Close History"' in PANEL_HTML_ONLY
    assert 'title="Close History"' in PANEL_HTML_ONLY


def test_no_graph_panel_url_identity_canonicalizes_query_params():
    url_parser = GRAPH_ARTIFACTS_JS.split("function parseUrlParts(url)", 1)[0]
    parse_url_parts = GRAPH_ARTIFACTS_JS.split("function parseUrlParts(url)", 1)[1].split(
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


def test_no_graph_panel_static_assets_are_served():
    client = TestClient(app)
    for path, expected in (
        ("/static/panel.css", "text/css"),
        ("/static/graph/graph-artifacts.js", "javascript"),
        ("/static/graph/graph-right-panel.js", "javascript"),
        ("/static/no_graph.js", "javascript"),
        *[(f"/shared-static/panel/{name}", "javascript") for name in _SHARED_PANEL_JS_PARTS],
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert expected in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-store"

    html = client.get("/")
    assert html.status_code == 200
    assert html.headers["cache-control"] == "no-store"
    for asset in ("panel.css", "graph/graph-artifacts.js", "graph/graph-right-panel.js", "no_graph.js"):
        assert re.search(rf"/static/{re.escape(asset)}\?v=\d+", html.text)
    for asset in (f"panel/{name}" for name in _SHARED_PANEL_JS_PARTS):
        assert re.search(rf"/shared-static/{re.escape(asset)}\?v=\d+", html.text)
    assert "/static/panel.js" not in html.text


def test_no_graph_panel_action_replay_autoplays_and_scales_with_right_panel():
    video_card = GRAPH_ARTIFACTS_JS.split("function renderActionReplayVideoCard(label, href)", 1)[1].split(
        "function renderActionReplayCard", 1
    )[0]
    assert (
        '<video controls autoplay muted playsinline preload="auto" src="${safeHref}" '
        'data-action-replay-video="true"></video>'
    ) in video_card

    assert ".artifact-primary .artifact-card {" in PANEL_CSS
    assert "width: 100%;" in PANEL_CSS.split(".artifact-primary .artifact-card {", 1)[1].split("}", 1)[0]

    primary_media_css = PANEL_CSS.split(".artifact-primary img,", 1)[1].split("}", 1)[0]
    assert ".artifact-primary video" in primary_media_css
    assert "max-height: none;" in primary_media_css
    assert "height: auto;" in primary_media_css


def test_no_graph_panel_history_drawer_styles_are_available():
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
