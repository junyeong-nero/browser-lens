const dot         = document.getElementById('dot');
const statusLabel = document.getElementById('status-label');
const timeline    = document.getElementById('timeline');
const emptyState  = document.getElementById('empty-state');
const input       = document.getElementById('input');
const btn         = document.getElementById('btn');
const btnIconPath = document.getElementById('btn-icon-path');
const statusLoading = document.getElementById('status-loading');
const inputShell  = document.getElementById('input-shell');
const agentModel  = document.getElementById('agent-model');
const sessionsBtn = document.getElementById('sessions-btn');
const sessionsPanel = document.getElementById('sessions-panel');
const sessionsClose = document.getElementById('sessions-close');
const sessionsList = document.getElementById('sessions-list');
const sessionsSearch = document.getElementById('sessions-search');
const sessionsSummary = document.getElementById('sessions-summary');
const liveBtn = document.getElementById('live-btn');
const replayControls = document.getElementById('replay-controls');
const replayPrev = document.getElementById('replay-prev');
const replayPlay = document.getElementById('replay-play');
const replayNext = document.getElementById('replay-next');
const replaySpeed = document.getElementById('replay-speed');
const replaySlider = document.getElementById('replay-slider');
const replayProgress = document.getElementById('replay-progress');
const statsEmpty = document.getElementById('stats-empty');
const statsContent = document.getElementById('stats-content');
const statsOverview = document.getElementById('stats-overview');
const statsToolChart = document.getElementById('stats-tool-chart');
const statsBehaviorChart = document.getElementById('stats-behavior-chart');
const statsDiagnostics = document.getElementById('stats-diagnostics');
const statsHelpBtn = document.getElementById('stats-help-btn');
const statsHelpPanel = document.getElementById('stats-help-panel');
const statsHelpClose = document.getElementById('stats-help-close');
const statsHelpCard = statsHelpPanel ? statsHelpPanel.querySelector('.stats-help-card') : null;

const sideTask       = document.getElementById('side-task');
const sidePlan       = document.getElementById('side-plan');
const sideSelection  = document.getElementById('side-selection');
const sideReplay     = document.getElementById('side-replay');
const sideStepTitle  = document.getElementById('side-step-title');
const metaStep       = document.getElementById('meta-step');
const metaUrl        = document.getElementById('meta-url');
const metaState      = document.getElementById('meta-state');

let isRunning = false;
let isSubmitting = false;
let isStopping = false;
let inputAllowed = false;
let reconnectDelay = 1000;
let ws = null;
let replayMode = false;
let replayPaused = true;
let replayEvents = [];
let replayIndex = 0;
let replayTimer = null;
let replaySessionId = null;
let liveSessionId = null;
let liveIsRunning = false;
let statsHelpPreviousFocus = null;

let subgoals = [];
let subgoalStartRowsById = new Map();
let pendingReplanFailedSubgoalId = null;
let actionSummariesByStep = new Map();
let actionSummaryCardsByStep = new Map();
let reasoningByStep = new Map();
let functionCallsByStep = new Map();
let observedUrlsByStep = new Map();
let actionShotsByStep = new Map();
let artifactsByStep = new Map();
let llmInferencesByStep = new Map();
let actionExecutionsByStep = new Map();
let stepErrorsByStep = new Map();
let pendingAgentFinalMessage = null;
let statsRenderDirty = false;

let currentTimelineStepId = null;
let currentTimelineStepGroup = null;
let selectedTimelineStepId = null;

// ── WebSocket ──────────────────────────────────────────
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    reconnectDelay = 1000;
    if (replayMode) {
      setReplayUi(true);
    } else {
      setStatus('connected', 'ready');
      if (!isRunning) setInputEnabled(true);
    }
  };
  ws.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      if (ev.type === 'task_started') liveIsRunning = true;
      if (ev.type === 'task_complete' || ev.type === 'task_failed' || ev.type === 'task_interrupted') liveIsRunning = false;
      if (replayMode) return;
      handleEvent(ev);
    } catch (_) {}
  };
  ws.onclose = () => {
    if (!replayMode) {
      setStatus('disconnected', 'disconnected');
      setInputEnabled(false);
    }
    setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
      connect();
    }, reconnectDelay);
  };
}

function setStatus(state, label) {
  dot.className = `status-dot ${state}`;
  statusLoading.classList.toggle('active', state === 'running');
  statusLabel.textContent = label;
  metaState.textContent = label;
}

function updateControlStates() {
  const stopMode = isRunning && !replayMode;
  const canRun = inputAllowed && !stopMode && !isSubmitting;
  btn.disabled = stopMode ? isStopping : !canRun;
  btn.classList.toggle('stop', stopMode);
  btn.setAttribute('aria-label', stopMode ? 'Stop task' : 'Run task');
  btn.setAttribute('title', stopMode ? 'Stop task' : 'Run task');
  btnIconPath.setAttribute('d', stopMode ? 'M6 6h12v12H6z' : 'M8 5v14l11-7z');
}

function setInputEnabled(enabled) {
  inputAllowed = enabled;
  input.disabled = !enabled;
  const inputLocked = !enabled && (isRunning || isSubmitting) && !replayMode;
  const composerDisabled = !enabled && !inputLocked;
  inputShell.classList.toggle('input-locked', inputLocked);
  inputShell.classList.toggle('composer-disabled', composerDisabled);
  updateControlStates();
}

function finishTaskUi(activeSubgoalStatus) {
  isRunning = false;
  isSubmitting = false;
  isStopping = false;
  clearGraphRunningStep();
  setStatus('connected', 'ready');
  setInputEnabled(true);
  subgoals.forEach(sg => { if (sg.status === 'active') sg.status = activeSubgoalStatus; });
  renderPlan();
}

function dispatchTrajectoryOutcome(outcome) {
  if (typeof window.setTrajectoryOutcome === 'function') {
    window.setTrajectoryOutcome(outcome);
  }
}

function resetTimeline() {
  timeline.replaceChildren();
  currentTimelineStepId = null;
  currentTimelineStepGroup = null;
  selectedTimelineStepId = null;
  subgoalStartRowsById = new Map();
}

function setAgentModel(modelName) {
  if (modelName) agentModel.textContent = modelName;
}
