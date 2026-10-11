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

// ── Timeline helpers ───────────────────────────────────
function clearEmpty() {
  if (emptyState && emptyState.parentNode) emptyState.remove();
}

function appendTimelineElement(el) {
  if (currentTimelineStepGroup) currentTimelineStepGroup.appendChild(el);
  else timeline.appendChild(el);
  timeline.scrollTop = timeline.scrollHeight;
}

function beginActionStepGroup(stepId) {
  currentTimelineStepId = stepId;
  setGraphRunningStep(stepId);
  currentTimelineStepGroup = document.createElement('div');
  currentTimelineStepGroup.className = 'action-step-group';
  currentTimelineStepGroup.dataset.stepId = String(stepId);
  currentTimelineStepGroup.addEventListener('click', () => {
    selectTimelineActionStep(stepId);
  });
  timeline.appendChild(currentTimelineStepGroup);
  timeline.scrollTop = timeline.scrollHeight;
  updateTimelineHighlight();
}

function finishActionStepGroup(stepId) {
  if (currentTimelineStepId != null && String(currentTimelineStepId) === String(stepId)) {
    currentTimelineStepId = null;
    currentTimelineStepGroup = null;
  }
  clearGraphRunningStep(stepId);
}

function timelineStepGroupHasMeaningfulChildren(group) {
  if (!group) return false;
  return Array.from(group.children).some(child => !child.classList.contains('action-summary-card'));
}

function removeNonActionStep(stepId) {
  const key = stepKey(stepId);
  if (key == null) return;

  const card = actionSummaryCardsByStep.get(key);
  if (card) card.remove();
  actionSummaryCardsByStep.delete(key);
  actionSummariesByStep.delete(key);
  reasoningByStep.delete(key);
  functionCallsByStep.delete(key);
  observedUrlsByStep.delete(key);
  actionShotsByStep.delete(key);
  artifactsByStep.delete(key);
  llmInferencesByStep.delete(key);
  actionExecutionsByStep.delete(key);

  const group = timelineGroupForStep(key);
  if (group && !timelineStepGroupHasMeaningfulChildren(group)) group.remove();

  if (selectedTimelineStepId === key) {
    if (typeof clearGraphSelection === 'function') clearGraphSelection();
    highlightTimelineActionStep(null);
    renderEmptyAdditionalInfo();
  }
}

function highlightedTimelineGroup() {
  if (selectedTimelineStepId == null) return null;
  return timeline.querySelector(`.action-step-group[data-step-id="${CSS.escape(String(selectedTimelineStepId))}"]`);
}

function scrollHighlightedTimelineStep() {
  const group = highlightedTimelineGroup();
  if (!group || !document.body.classList.contains('view-timeline')) return;
  group.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function updateTimelineHighlight() {
  timeline.querySelectorAll('.action-step-group.timeline-highlight').forEach(el => {
    el.classList.remove('timeline-highlight');
  });
  const group = highlightedTimelineGroup();
  if (group) group.classList.add('timeline-highlight');
  actionSummaryCardsByStep.forEach((card, key) => {
    card.classList.toggle('selected', selectedTimelineStepId === key);
  });
}

function highlightTimelineActionStep(stepId) {
  selectedTimelineStepId = stepId != null ? String(stepId) : null;
  updateTimelineHighlight();
  scrollHighlightedTimelineStep();
}

function subgoalKey(subgoalId) {
  return subgoalId != null ? String(subgoalId) : null;
}

function recordSubgoalStart(subgoalId, row) {
  const key = subgoalKey(subgoalId);
  if (key == null || !row) return;
  row.dataset.subgoalId = key;
  row.classList.add('subgoal-anchor');
  row.setAttribute('tabindex', '-1');
  subgoalStartRowsById.set(key, row);
  renderPlan();
}

function flashSubgoalStartRow(row) {
  timeline.querySelectorAll('.row.subgoal-anchor.subgoal-jump-highlight').forEach(el => {
    el.classList.remove('subgoal-jump-highlight');
  });
  row.classList.remove('subgoal-jump-highlight');
  void row.offsetWidth;
  row.classList.add('subgoal-jump-highlight');
  row.addEventListener('animationend', () => {
    row.classList.remove('subgoal-jump-highlight');
  }, { once: true });
}

function jumpToSubgoalStart(subgoalId) {
  const key = subgoalKey(subgoalId);
  if (key == null) return;
  const row = subgoalStartRowsById.get(key) ||
    timeline.querySelector(`.row.subgoal-anchor[data-subgoal-id="${CSS.escape(key)}"]`);
  if (!row) return;
  activateMainView('timeline', { scrollSelection: false });
  flashSubgoalStartRow(row);
  row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  try { row.focus({ preventScroll: true }); } catch (_) {}
}
