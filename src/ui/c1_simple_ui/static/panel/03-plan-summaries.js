function setSideTask(query) {
  sideTask.className = '';
  sideTask.textContent = query;
}

function setSubgoals(list) {
  subgoals = (list || []).map(sg => ({
    id: sg.id,
    description: sg.description,
    status: 'pending',
  }));
  renderPlan();
}

function replaceSubgoalsAfterFailed(failedId, revisedList) {
  const failedIdx = subgoals.findIndex(s => String(s.id) === String(failedId));
  if (failedIdx === -1) {
    setSubgoals(revisedList);
    return;
  }
  const revisedSubgoals = (revisedList || []).map(sg => ({
    id: sg.id,
    description: sg.description,
    status: 'pending',
  }));
  subgoals = subgoals.slice(0, failedIdx + 1).concat(revisedSubgoals);
  renderPlan();
}

function updateSubgoalStatus(id, status) {
  const sg = subgoals.find(s => String(s.id) === String(id));
  if (sg) { sg.status = status; renderPlan(); }
}

function renderPlan() {
  if (!subgoals.length) {
    sidePlan.innerHTML = '<div class="side-empty">no plan yet.</div>';
    return;
  }
  const statusIcons = {
    pending: '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z"></path></svg>',
    active: '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M8 5v14l11-7z"></path></svg>',
    done: '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1.2 13.6-3.4-3.4 1.4-1.4 2 2 4.6-4.6 1.4 1.4-6 6z"></path></svg>',
    failed: '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm3.5 12.1-1.4 1.4L12 13.4l-2.1 2.1-1.4-1.4 2.1-2.1-2.1-2.1 1.4-1.4 2.1 2.1 2.1-2.1 1.4 1.4-2.1 2.1 2.1 2.1z"></path></svg>',
  };
  sidePlan.innerHTML = subgoals.map(sg => {
    const key = subgoalKey(sg.id);
    const jumpable = key != null && subgoalStartRowsById.has(key);
    const disabled = jumpable ? '' : ' disabled aria-disabled="true"';
    return `
    <button type="button" class="todo ${sg.status}${jumpable ? ' jumpable' : ''}" data-subgoal-id="${escHtml(key || '')}"${disabled} aria-label="Jump to subgoal ${escHtml(key || '')} start">
      <span class="status-icon">${statusIcons[sg.status] || statusIcons.pending}</span>
      <span class="text">${escHtml(sg.description)}</span>
    </button>`;
  }).join('');
  sidePlan.querySelectorAll('[data-subgoal-id]').forEach(item => {
    item.addEventListener('click', () => jumpToSubgoalStart(item.getAttribute('data-subgoal-id')));
  });
}

function stepKey(stepId) {
  return stepId != null ? String(stepId) : null;
}

function timelineGroupForStep(stepId) {
  const key = stepKey(stepId);
  if (key == null) return null;
  return timeline.querySelector(`.action-step-group[data-step-id="${CSS.escape(key)}"]`);
}

function createActionSummaryCard(key) {
  const template = document.createElement('template');
  template.innerHTML = `<div role="button" tabindex="0" class="action-summary-card" data-step-id="${escHtml(key)}"></div>`;
  const card = template.content.firstElementChild;
  card.addEventListener('click', (event) => {
    event.stopPropagation();
    selectTimelineActionStep(key);
  });
  card.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      selectTimelineActionStep(key);
    }
  });
  return card;
}

function renderActionSummaryCard(card, item) {
  const key = stepKey(item.step);
  const phaseName = item.phaseId ? String(item.phaseId).replace(/^phase-/, '').replace(/[^a-z0-9_-]/gi, '') : '';
  const phaseCls = phaseName ? ` phase-${phaseName}` : '';
  const what = item.what || item.actionSummary || `Step ${item.step}`;
  const outcome = (item.outcome && item.outcome !== '—')
    ? `<span class="outcome">${escHtml(item.outcome)}</span>`
    : '';

  card.className = `action-summary-card${phaseCls}`;
  card.classList.toggle('selected', selectedTimelineStepId === key);
  card.dataset.stepId = key || '';
  card.innerHTML = `
    <span class="summary-head">
      <span class="step-no">#${escHtml(item.step)}</span>
      <span class="summary-copy">
        <span class="what">${escHtml(what)}</span>
        ${outcome}
      </span>
    </span>`;
}

function refreshActionSummaryForStep(stepId) {
  const key = stepKey(stepId);
  if (key == null) return;
  const item = actionSummariesByStep.get(key);
  const card = actionSummaryCardsByStep.get(key);
  if (item && card) renderActionSummaryCard(card, item);
  refreshAdditionalInfoForStep(stepId);
}

function storeStepReasoning(stepId, reasoning) {
  const key = stepKey(stepId);
  if (key == null || !reasoning) return;
  reasoningByStep.set(key, reasoning);
  refreshActionSummaryForStep(stepId);
}

function storeFunctionCalls(stepId, calls) {
  const key = stepKey(stepId);
  if (key == null) return;
  functionCallsByStep.set(key, Array.isArray(calls) ? calls : []);
  refreshActionSummaryForStep(stepId);
  if (selectedTimelineStepId == null && artifactsByStep.has(key)) {
    renderActionStepAdditionalInfo(key);
  }
}

function storeActionExecutionForStats(ev) {
  const key = stepKey(ev && ev.step_id);
  if (key == null || !ev || !ev.action) return;
  const executions = actionExecutionsByStep.get(key) || [];
  executions.push(ev.action);
  actionExecutionsByStep.set(key, executions);
}

function storeObservedUrl(stepId, url) {
  const key = stepKey(stepId);
  if (key == null || !url) return;
  observedUrlsByStep.set(key, url);
  refreshActionSummaryForStep(stepId);
}

function storeActionShot(stepId, href) {
  const key = stepKey(stepId);
  if (key == null || !href) return;
  actionShotsByStep.set(key, href);
  refreshActionSummaryForStep(stepId);
}

function storeArtifactsForStep(stepId, artifacts) {
  const key = stepKey(stepId);
  if (key == null || !artifacts) return;
  const prev = artifactsByStep.get(key) || {};
  artifactsByStep.set(key, { ...prev, ...artifacts });
  if (selectedTimelineStepId == null) {
    renderActionStepAdditionalInfo(key);
  } else {
    refreshAdditionalInfoForStep(stepId);
  }
}

function upsertActionSummary(item) {
  const key = stepKey(item.step);
  if (key == null) return;
  const next = { ...(actionSummariesByStep.get(key) || {}), ...item };
  actionSummariesByStep.set(key, next);

  let card = actionSummaryCardsByStep.get(key);
  if (!card) {
    card = createActionSummaryCard(key);
    actionSummaryCardsByStep.set(key, card);
    const group = timelineGroupForStep(key);
    if (currentTimelineStepGroup && stepKey(currentTimelineStepId) === key) currentTimelineStepGroup.appendChild(card);
    else if (group) group.appendChild(card);
    else appendTimelineElement(card);
  }

  renderActionSummaryCard(card, next);
  refreshAdditionalInfoForStep(key);
  timeline.scrollTop = timeline.scrollHeight;
}

// Tab switching (Timeline ↔ Graph)
