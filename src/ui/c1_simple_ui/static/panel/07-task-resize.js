async function submitTask() {
  const query = input.value.trim();
  if (!query || isRunning || isSubmitting) return;
  isSubmitting = true;
  isStopping = false;
  setStatus('running', 'submitting…');
  setInputEnabled(false);
  try {
    const res = await fetch('/task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Task rejected');
    input.value = '';
    autoResize();
  } catch (e) {
    isSubmitting = false;
    setStatus(ws && ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected', ws && ws.readyState === WebSocket.OPEN ? 'ready' : 'disconnected');
    setInputEnabled(ws && ws.readyState === WebSocket.OPEN && !replayMode);
    addBlock('red', `<div class="title">network error</div><div class="meta">${escHtml(e.message || 'failed to submit task. is the server running?')}</div>`);
  }
}

async function interruptTask() {
  if ((!isRunning && !isSubmitting) || isStopping) return;
  isStopping = true;
  updateControlStates();
  setStatus('running', 'stopping…');
  addRow('warn', 'interrupt requested…');
  try {
    const res = await fetch('/interrupt', { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Interrupt rejected');
  } catch (e) {
    isStopping = false;
    updateControlStates();
    addBlock('red', `<div class="title">network error</div><div class="meta">${escHtml(e.message || 'failed to interrupt task. is the server running?')}</div>`);
  }
}

btn.addEventListener('click', () => {
  if (isRunning || isSubmitting) {
    interruptTask();
  } else {
    submitTask();
  }
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitTask();
  }
});

function autoResize() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
}
input.addEventListener('input', autoResize);

connect();

// ── Sidebar resize ─────────────────────────────────────
function setupPanelResizer({ id, storageKey, legacyStorageKey, cssVar, defaultWidth, widthFromPointer }) {
  const resizer = document.getElementById(id);
  if (!resizer) return;
  const MIN = 220, MAX = 720;

  const saved = parseInt(localStorage.getItem(storageKey) || localStorage.getItem(legacyStorageKey || '') || '', 10);
  if (saved && saved >= MIN && saved <= MAX) {
    document.body.style.setProperty(cssVar, saved + 'px');
  }

  let dragging = false;
  resizer.addEventListener('pointerdown', (e) => {
    dragging = true;
    resizer.classList.add('active');
    resizer.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    e.preventDefault();
  });
  resizer.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const w = Math.min(MAX, Math.max(MIN, widthFromPointer(e)));
    document.body.style.setProperty(cssVar, w + 'px');
  });
  const stop = (e) => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove('active');
    document.body.classList.remove('resizing');
    try { resizer.releasePointerCapture(e.pointerId); } catch (_) {}
    const cur = getComputedStyle(document.body).getPropertyValue(cssVar).trim();
    const px = parseInt(cur, 10);
    if (px) localStorage.setItem(storageKey, String(px));
  };
  resizer.addEventListener('pointerup', stop);
  resizer.addEventListener('pointercancel', stop);
  resizer.addEventListener('dblclick', () => {
    document.body.style.setProperty(cssVar, defaultWidth + 'px');
    localStorage.setItem(storageKey, String(defaultWidth));
  });
}

setupPanelResizer({
  id: 'left-resizer',
  storageKey: 'bragent.leftAsideW',
  cssVar: '--left-aside-w',
  defaultWidth: 320,
  widthFromPointer: (e) => e.clientX,
});

setupPanelResizer({
  id: 'right-resizer',
  storageKey: 'bragent.rightAsideW',
  legacyStorageKey: 'bragent.asideW',
  cssVar: '--right-aside-w',
  defaultWidth: 360,
  widthFromPointer: (e) => window.innerWidth - e.clientX,
});
