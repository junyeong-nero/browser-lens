import shutil
import subprocess
from pathlib import Path

import pytest


REPLAY_RENDERERS = (
    Path("src/ui/shared/static/panel/panel-replay.js"),
    Path("src/ui/c1_simple_ui/static/panel/06-replay.js"),
)


def _renderer_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("function showReplayMessage", 1)[0]


JS_HARNESS_PREFIX = r"""
const assert = require('assert');

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.eventListeners = {};
    this._innerHTML = '';
    this.className = '';
    this.type = '';
    this.textContent = '';
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
  }

  get innerHTML() {
    return this._innerHTML + this.children.map((child) => child.outerHTML).join('');
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, handler) {
    this.eventListeners[name] = handler;
  }

  outerAttrs() {
    const attrs = [];
    if (this.className) attrs.push(`class="${this.className}"`);
    if (this.type) attrs.push(`type="${this.type}"`);
    for (const [name, value] of Object.entries(this.attributes)) {
      attrs.push(`${name}="${value}"`);
    }
    return attrs.length ? ` ${attrs.join(' ')}` : '';
  }

  get outerHTML() {
    return `<${this.tagName}${this.outerAttrs()}>${this.innerHTML}</${this.tagName}>`;
  }
}

class FakeTemplate extends FakeElement {
  constructor() {
    super('template');
    this.content = { firstElementChild: null };
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    const match = this._innerHTML.match(/^<section class="([^"]+)"><h3>([\s\S]*)<\/h3><\/section>$/);
    const section = new FakeElement('section');
    if (match) {
      section.className = match[1];
      const heading = new FakeElement('h3');
      heading.innerHTML = match[2];
      section.appendChild(heading);
    } else {
      section.innerHTML = this._innerHTML;
    }
    this.content = { firstElementChild: section };
  }
}

const document = {
  createElement(tagName) {
    return tagName === 'template' ? new FakeTemplate() : new FakeElement(tagName);
  },
};

var sessionsList = new FakeElement('div');
var sessionsSummary = new FakeElement('div');
var replaySessionId = null;
var selectedSessionId = null;
function startReplay(sessionId) {
  selectedSessionId = sessionId;
}
"""


JS_HARNESS_SUFFIX = r"""
function isoForOffset(dayOffset, time) {
  const date = new Date();
  date.setDate(date.getDate() + dayOffset);
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return {
    id: `${yyyy}${mm}${dd}-${time.replaceAll(':', '')}`,
    startedAt: `${yyyy}-${mm}-${dd}T${time}`,
  };
}

async function main() {
  const today = isoForOffset(0, '14:36:55');
  const yesterday = isoForOffset(-1, '09:05:04');
  const sampleSessions = [
    {
      id: yesterday.id,
      started_at: yesterday.startedAt,
      query: 'Retry login with OpenRouter',
      model: 'openrouter/browser-agent',
      step_count: 3,
      has_events: false,
      video: null,
    },
    {
      id: today.id,
      started_at: today.startedAt,
      query: 'Inspect checkout failure',
      model: 'gpt-5.4',
      step_count: 7,
      has_events: true,
      video: 'video/session.webm',
    },
  ];

  let fetchCalls = [];
  fetch = async (url) => {
    fetchCalls.push(url);
    return { ok: true, json: async () => ({ sessions: sampleSessions }) };
  };
  replaySessionId = today.id;
  await loadSessions();

  assert.deepStrictEqual(fetchCalls, ['/sessions']);
  assert.strictEqual(sessionsSummary.textContent, '2 saved sessions');
  let html = sessionsList.innerHTML;
  assert(html.includes('<h3>Today</h3>'), html);
  assert(html.includes('<h3>Yesterday</h3>'), html);
  assert(html.indexOf('Inspect checkout failure') < html.indexOf('Retry login with OpenRouter'), html);
  assert(html.indexOf(today.id) < html.indexOf(yesterday.id), html);
  assert(html.includes('class="session-primary">Inspect checkout failure</span>'), html);
  assert(html.includes('aria-current="true"'), html);
  assert(html.includes('class="session-current-marker">Current</span>'), html);
  assert(html.includes('class="session-artifact-badge">events</span>'), html);
  assert(html.includes('class="session-artifact-badge">video</span>'), html);

  const currentButton = sessionsList.children[0].children.find((child) => child.tagName === 'button');
  currentButton.eventListeners.click();
  assert.strictEqual(selectedSessionId, today.id);

  sessionsSearchQuery = 'openrouter';
  renderSessions();
  html = sessionsList.innerHTML;
  assert.strictEqual(sessionsSummary.textContent, '1 of 2 sessions');
  assert(!html.includes('Inspect checkout failure'), html);
  assert(html.includes('Retry login with OpenRouter'), html);

  sessionsSearchQuery = today.id;
  renderSessions();
  html = sessionsList.innerHTML;
  assert(html.includes('Inspect checkout failure'), html);
  assert(!html.includes('Retry login with OpenRouter'), html);

  savedSessions = [
    {
      id: '20260614-000001',
      started_at: '2026-06-15T12:00:00',
      query: 'Path date first second',
      step_count: 1,
    },
    {
      id: '20260614-235959',
      started_at: '2026-06-13T12:00:00',
      query: 'Path date last second',
      step_count: 1,
    },
    {
      id: '20260613-235959',
      started_at: '2026-06-14T23:59:59',
      query: 'Previous path date',
      step_count: 1,
    },
  ];
  sessionsSearchQuery = '';
  renderSessions();
  html = sessionsList.innerHTML;
  assert.strictEqual(sessionDateKey(savedSessions[0]), '2026-06-14');
  assert.strictEqual(sessionDateKey(savedSessions[1]), '2026-06-14');
  assert.strictEqual(sessionDateKey(savedSessions[2]), '2026-06-13');
  assert.strictEqual(sessionsList.children.length, 2, html);
  const firstPathDateGroup = sessionsList.children[0];
  assert(firstPathDateGroup.innerHTML.includes('Path date last second'), html);
  assert(firstPathDateGroup.innerHTML.includes('Path date first second'), html);
  assert(!firstPathDateGroup.innerHTML.includes('Previous path date'), html);
  assert(
    firstPathDateGroup.innerHTML.indexOf('Path date last second') <
      firstPathDateGroup.innerHTML.indexOf('Path date first second'),
    firstPathDateGroup.innerHTML
  );

  sessionsSearchQuery = 'no matching session';
  renderSessions();
  assert.strictEqual(sessionsSummary.textContent, '0 of 3 sessions');
  assert(sessionsList.innerHTML.includes('No sessions match your search'), sessionsList.innerHTML);

  savedSessions = [];
  sessionsSearchQuery = '';
  renderSessions();
  assert.strictEqual(sessionsSummary.textContent, 'No saved sessions');
  assert(sessionsList.innerHTML.includes('No saved sessions'), sessionsList.innerHTML);

  fetch = async () => { throw new Error('network down'); };
  await loadSessions();
  assert.strictEqual(sessionsSummary.textContent, 'No saved sessions');
  assert(sessionsList.innerHTML.includes('Could not load saved sessions'), sessionsList.innerHTML);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""


@pytest.mark.parametrize("renderer_path", REPLAY_RENDERERS)
def test_history_drawer_renderer_filters_groups_and_marks_artifacts(renderer_path, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for BrowserLens panel renderer smoke tests")

    script = JS_HARNESS_PREFIX + "\n" + _renderer_source(renderer_path) + "\n" + JS_HARNESS_SUFFIX
    script_path = tmp_path / "history-drawer-renderer-check.js"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [node, str(script_path)],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
