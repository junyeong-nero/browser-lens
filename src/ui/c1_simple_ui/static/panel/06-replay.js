let savedSessions = [];
let sessionsSearchQuery = '';

function setReplayUi(active) {
  replayMode = active;
  liveBtn.hidden = !active;
  replayControls.classList.toggle('active', active);
  setInputEnabled(!active && !isRunning && ws && ws.readyState === WebSocket.OPEN);
  if (active) setStatus('connected', 'ready');
}

function replayDelay(prev, next) {
  if (!prev || !next) return 120;
  const speed = replaySpeed.value;
  if (speed === 'instant') return 0;
  const raw = Math.max(40, Math.min(1200, ((next.ts || 0) - (prev.ts || 0)) * 1000));
  return raw / Number(speed || 1);
}

function updateReplaySliderProgress() {
  const max = Number(replaySlider.max || 0);
  const value = Number(replaySlider.value || 0);
  const progress = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  replaySlider.style.setProperty('--replay-slider-progress', `${progress}%`);
}

function updateReplayProgress() {
  replaySlider.max = String(Math.max(0, replayEvents.length));
  replaySlider.value = String(replayIndex);
  updateReplaySliderProgress();
  replayProgress.textContent = `${replayIndex}/${replayEvents.length}`;
}

function dispatchReplayEvent(ev) {
  handleEvent(ev);
  setReplayUi(true);
}

function replayStepForward() {
  if (replayIndex >= replayEvents.length) {
    replayPaused = true;
    updateReplayProgress();
    return;
  }
  const prev = replayEvents[replayIndex - 1];
  const ev = replayEvents[replayIndex];
  replayIndex += 1;
  dispatchReplayEvent(ev);
  updateReplayProgress();
  if (!replayPaused) {
    const next = replayEvents[replayIndex];
    replayTimer = setTimeout(replayStepForward, replayDelay(prev || ev, next || ev));
  }
}

function replayTo(index) {
  clearTimeout(replayTimer);
  replayPaused = true;
  const target = Math.max(0, Math.min(index, replayEvents.length));
  resetTimeline();
  resetSidebar();
  setReplayUi(true);
  replayIndex = 0;
  while (replayIndex < target) replayStepForward();
  replayPaused = true;
  updateReplayProgress();
}

function setSessionsMessage(message) {
  sessionsList.innerHTML = `<div class="sessions-message">${escHtml(message)}</div>`;
}

function sessionSearchText(session) {
  return [session.query, session.id, session.model]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function sessionMatchesSearch(session, query) {
  const normalized = (query || '').trim().toLowerCase();
  if (!normalized) return true;
  return sessionSearchText(session).includes(normalized);
}

function parseSessionDateValue(raw) {
  const text = String(raw || '');
  if (!text) return null;
  const logNameMatch = text.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (logNameMatch) {
    const [, year, month, day, hour, minute, second] = logNameMatch;
    const parsed = new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second)
    );
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  const direct = new Date(text);
  return Number.isNaN(direct.getTime()) ? null : direct;
}

function parseSessionDate(session) {
  return parseSessionDateValue(session && session.id) ||
    parseSessionDateValue(session && session.started_at);
}

function sessionDateKey(session) {
  const date = parseSessionDate(session);
  if (!date) return 'unknown';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function sessionDateLabel(session) {
  const date = parseSessionDate(session);
  if (!date) return 'Older';
  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((todayStart - dateStart) / 86400000);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatSessionTime(session) {
  const date = parseSessionDate(session);
  if (!date) return escHtml(session.started_at || session.id || 'unknown time');
  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((todayStart - dateStart) / 86400000);
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  if (diffDays === 0) return escHtml(time);
  if (diffDays === 1) return escHtml(`Yesterday ${time}`);
  return escHtml(date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));
}

function sessionLogName(session) {
  return String(session && session.id ? session.id : '');
}

function compareSessionsByLogNameDesc(left, right) {
  const leftName = sessionLogName(left);
  const rightName = sessionLogName(right);
  if (leftName === rightName) return 0;
  return leftName > rightName ? -1 : 1;
}

function groupSessionsByDate(sessions) {
  const groups = [];
  const index = new Map();
  sessions.forEach((session) => {
    const key = sessionDateKey(session);
    if (!index.has(key)) {
      const group = { key, label: sessionDateLabel(session), sessions: [] };
      index.set(key, group);
      groups.push(group);
    }
    index.get(key).sessions.push(session);
  });
  return groups;
}

function updateSessionsSummary(total, visible) {
  if (!sessionsSummary) return;
  if (!total) {
    sessionsSummary.textContent = 'No saved sessions';
    return;
  }
  sessionsSummary.textContent = visible === total
    ? `${total} saved sessions`
    : `${visible} of ${total} sessions`;
}

function sessionMetaHtml(session) {
  const parts = [
    `<span>${formatSessionTime(session)}</span>`,
    `<span>${escHtml(session.step_count || 0)} actions</span>`,
  ];
  if (session.model) parts.push(`<span>${escHtml(session.model)}</span>`);
  if (session.has_events) parts.push('<span class="session-artifact-badge">events</span>');
  if (session.video) parts.push('<span class="session-artifact-badge">video</span>');
  parts.push(`<span>${escHtml(session.id || 'unknown session')}</span>`);
  return parts.join('');
}

function renderSessionButton(session) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'session-item';
  const query = session.query || 'unknown task';
  const isCurrent = session.id === replaySessionId;
  if (isCurrent) btn.setAttribute('aria-current', 'true');
  btn.innerHTML =
    `<div class="session-main-row">` +
      `<span class="session-primary">${escHtml(query.slice(0, 160))}</span>` +
      `${isCurrent ? '<span class="session-current-marker">Current</span>' : ''}` +
    `</div>` +
    `<div class="session-meta">${sessionMetaHtml(session)}</div>`;
  btn.addEventListener('click', () => startReplay(session.id));
  return btn;
}

function renderSessions() {
  const visibleSessions = savedSessions
    .filter((session) => sessionMatchesSearch(session, sessionsSearchQuery))
    .sort(compareSessionsByLogNameDesc);
  updateSessionsSummary(savedSessions.length, visibleSessions.length);
  if (!savedSessions.length) {
    setSessionsMessage('No saved sessions');
    return;
  }
  if (!visibleSessions.length) {
    setSessionsMessage('No sessions match your search');
    return;
  }
  sessionsList.innerHTML = '';
  groupSessionsByDate(visibleSessions).forEach((group) => {
    const template = document.createElement('template');
    template.innerHTML = `<section class="session-date-group"><h3>${escHtml(group.label)}</h3></section>`;
    const section = template.content.firstElementChild;
    group.sessions.forEach((session) => section.appendChild(renderSessionButton(session)));
    sessionsList.appendChild(section);
  });
}

async function loadSessions() {
  setSessionsMessage('Loading saved sessions');
  updateSessionsSummary(savedSessions.length, savedSessions.length);
  let data = {};
  try {
    const res = await fetch('/sessions');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (_) {
    savedSessions = [];
    updateSessionsSummary(0, 0);
    setSessionsMessage('Could not load saved sessions');
    return;
  }
  savedSessions = Array.isArray(data.sessions) ? data.sessions : [];
  renderSessions();
}

function showReplayMessage(title, detail, cls = 'red') {
  clearTimeout(replayTimer);
  replayPaused = true;
  resetTimeline();
  resetSidebar();
  setReplayUi(true);
  updateReplayProgress();
  addBlock(cls, `<div class="title">${escHtml(title)}</div><div class="meta">${escHtml(detail)}</div>`);
}

async function startReplay(sessionId) {
  clearTimeout(replayTimer);
  replaySessionId = sessionId;
  replayEvents = [];
  replayIndex = 0;
  replayPaused = true;
  resetTimeline();
  resetSidebar();
  setReplayUi(true);
  updateReplayProgress();
  closeSessionsPanel();
  try {
    const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/events`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    replayEvents = Array.isArray(data.events) ? data.events : [];
    replayIndex = 0;
    replayPaused = true;
    updateReplayProgress();
    if (!replayEvents.length) {
      showReplayMessage('No replay events.', `Session ${sessionId} has no replay events.`, 'plain');
      return;
    }
    replayTo(replayEvents.length);
  } catch (err) {
    replayEvents = [];
    replayIndex = 0;
    showReplayMessage('Could not load replay session', err && err.message ? err.message : `Session ${sessionId} could not be loaded.`);
  }
}

function closeSessionsPanel() {
  sessionsPanel.classList.add('hidden');
}

function openSessionsPanel() {
  sessionsPanel.classList.remove('hidden');
  sessionsSearchQuery = sessionsSearch ? sessionsSearch.value : '';
  loadSessions();
  if (sessionsSearch) requestAnimationFrame(() => sessionsSearch.focus());
}

function isSessionsPanelTarget(target) {
  if (!(target instanceof Node)) return false;
  return sessionsPanel.contains(target) || sessionsBtn.contains(target);
}

sessionsBtn.addEventListener('click', () => {
  if (sessionsPanel.classList.contains('hidden')) {
    openSessionsPanel();
  } else {
    closeSessionsPanel();
  }
});
sessionsClose.addEventListener('click', closeSessionsPanel);
if (sessionsSearch) {
  sessionsSearch.addEventListener('input', () => {
    sessionsSearchQuery = sessionsSearch.value;
    renderSessions();
  });
}
document.addEventListener('pointerdown', (event) => {
  if (sessionsPanel.classList.contains('hidden')) return;
  if (isSessionsPanelTarget(event.target)) return;
  closeSessionsPanel();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeSessionsPanel();
});
liveBtn.addEventListener('click', () => {
  clearTimeout(replayTimer);
  replayPaused = true;
  replayEvents = [];
  replayIndex = 0;
  replaySessionId = null;
  resetTimeline();
  resetSidebar();
  setReplayUi(false);
  isRunning = liveIsRunning;
  if (isRunning) {
    setStatus('running', 'running');
    setInputEnabled(false);
  } else {
    setStatus(ws && ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected', ws && ws.readyState === WebSocket.OPEN ? 'ready' : 'disconnected');
    setInputEnabled(ws && ws.readyState === WebSocket.OPEN);
  }
});
replayPlay.addEventListener('click', () => {
  replayPaused = !replayPaused;
  clearTimeout(replayTimer);
  if (!replayPaused) replayStepForward();
});
replayNext.addEventListener('click', () => {
  replayPaused = true;
  clearTimeout(replayTimer);
  replayStepForward();
});
replayPrev.addEventListener('click', () => replayTo(Math.max(0, replayIndex - 1)));
replaySlider.addEventListener('input', () => replayTo(Number(replaySlider.value || 0)));

// ── Task submission ────────────────────────────────────
