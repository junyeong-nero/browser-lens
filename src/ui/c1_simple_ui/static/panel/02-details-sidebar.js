function renderEmptyAdditionalInfo(message = 'no action step selected.') {
  const empty = `<div class="side-empty">${escHtml(message)}</div>`;
  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title side-empty';
    sideStepTitle.textContent = message;
  }
  if (sideReplay) sideReplay.innerHTML = empty;
  renderSimpleActionDetails([]);
  if (sideSelection) sideSelection.innerHTML = empty;
  if (typeof renderRightPanelAuxiliarySections === 'function') {
    renderRightPanelAuxiliarySections(null, null);
  }
}

function renderAdditionalInfoRow(label, value) {
  return `<div class="bullet"><span class="dot">•</span><span><span class="k">${escHtml(label)}</span> <span class="v">${escHtml(value)}</span></span></div>`;
}

function functionCallNames(calls) {
  if (!calls.length) return '—';
  return calls.map((call, index) => call && call.name ? call.name : `call ${index + 1}`).join(', ');
}

function functionCallArguments(calls) {
  if (!calls.length) return '—';
  return calls.map((call, index) => {
    const name = call && call.name ? call.name : `call ${index + 1}`;
    const args = call && call.args && Object.keys(call.args).length ? formatArgs(call.args) : '—';
    return `${name}: ${args}`;
  }).join('; ');
}

function renderSimpleActionDetails(calls) {
  if (!simpleActionDetails) return;
  const items = Array.isArray(calls) ? calls : [];
  if (!items.length) {
    simpleActionDetails.innerHTML = '<div class="side-empty">no tool call selected.</div>';
    return;
  }
  simpleActionDetails.innerHTML = items.map((call, index) => {
    const name = call && call.name ? call.name : `call ${index + 1}`;
    const args = call && call.args && Object.keys(call.args).length ? formatArgs(call.args) : '—';
    return `
      <div class="simple-tool-card">
        <div class="simple-tool-row"><span class="simple-tool-label">tool</span><code>${escHtml(name)}</code></div>
        <div class="simple-tool-row simple-tool-args"><span class="simple-tool-label">arguments</span><pre>${escHtml(args)}</pre></div>
      </div>`;
  }).join('');
}

function renderActionStepAdditionalInfo(stepId) {
  const key = stepKey(stepId);
  if (key == null) {
    renderEmptyAdditionalInfo();
    return;
  }
  const item = actionSummariesByStep.get(key) || { step: key, what: `Step ${key}` };
  const what = item.what || item.actionSummary || `Step ${key}`;
  const reasoning = reasoningByStep.get(key) || item.reason || item.why || '';
  const calls = functionCallsByStep.get(key) || [];
  const url = observedUrlsByStep.get(key);
  const artifacts = artifactsByStep.get(key) || null;
  const inference = getLlmInferenceForStep(key);

  const rows = [
    renderAdditionalInfoRow('Action step number', `#${key}`),
    renderAdditionalInfoRow('Summary', what),
    renderAdditionalInfoRow('Outcome', item.outcome && item.outcome !== '—' ? item.outcome : '—'),
    renderAdditionalInfoRow('Reasoning', reasoning || '—'),
    renderAdditionalInfoRow('Function call', functionCallNames(calls)),
    renderAdditionalInfoRow('Function call arguments', functionCallArguments(calls)),
  ];
  if (url) rows.push(renderAdditionalInfoRow('Observed URL', url));

  const replayBody = artifacts ? renderActionArtifacts(artifacts) : '';

  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title';
    sideStepTitle.textContent = `Action step #${key}`;
  }
  if (sideReplay) {
    sideReplay.innerHTML = replayBody || '<div class="side-empty">no screenshot available.</div>';
  }
  renderSimpleActionDetails(calls);
  if (sideSelection) {
    sideSelection.innerHTML = rows.length ? rows.join('') : '<div class="side-empty">no info.</div>';
  }
  if (typeof renderRightPanelAuxiliarySections === 'function') {
    renderRightPanelAuxiliarySections(inference, artifacts);
  }
}

function actionGroupStepIds(actionNode) {
  const ids = Array.isArray(actionNode && actionNode.stepIds)
    ? actionNode.stepIds.map(stepKey).filter(key => key != null)
    : [];
  const fallback = stepKey(actionNode && (actionNode.step ?? actionNode.lastStep ?? actionNode.firstStep));
  if (!ids.length && fallback != null) ids.push(fallback);
  return ids;
}

function summaryForActionStep(stepId) {
  const item = actionSummariesByStep.get(stepId);
  return (item && (item.what || item.actionSummary)) || `Step ${stepId}`;
}

function renderActionGroupAdditionalInfo(actionNode) {
  if (!actionNode) {
    renderEmptyAdditionalInfo();
    return;
  }

  const stepIds = actionGroupStepIds(actionNode);
  const latestStepId = stepIds.length ? stepIds[stepIds.length - 1] : null;
  const latestItem = latestStepId != null ? actionSummariesByStep.get(latestStepId) : null;
  const representative = actionNode.label || (latestStepId != null ? summaryForActionStep(latestStepId) : 'Action group');
  const summary = stepIds.length > 1 ? `${stepIds.length} related action steps` : representative;
  const reasoning = (latestStepId != null && reasoningByStep.get(latestStepId)) ||
    (latestItem && (latestItem.reason || latestItem.why)) ||
    '';
  const calls = (latestStepId != null && functionCallsByStep.get(latestStepId)) ||
    (actionNode.actionName ? [{ name: actionNode.actionName, args: actionNode.args || {} }] : []);
  const artifacts = (latestStepId != null && artifactsByStep.get(latestStepId)) || actionNode.artifacts || null;
  const inference = (latestStepId != null && getLlmInferenceForStep(latestStepId)) || actionNode.llmInference || null;
  const stepList = stepIds.length ? stepIds.map(id => `#${id}`).join(', ') : '—';

  const rows = [
    renderAdditionalInfoRow('Action steps', stepList),
    renderAdditionalInfoRow('Summary', summary),
    renderAdditionalInfoRow('Outcome', latestItem && latestItem.outcome && latestItem.outcome !== '—' ? latestItem.outcome : '—'),
    renderAdditionalInfoRow('Reasoning', reasoning || '—'),
    renderAdditionalInfoRow('Function call', functionCallNames(calls)),
    renderAdditionalInfoRow('Function call arguments', functionCallArguments(calls)),
  ];

  const memberList = stepIds.length
    ? `<div class="action-member-list" aria-label="Action group member steps">${stepIds.map(stepId => {
        const selected = selectedTimelineStepId === stepId ? ' selected' : '';
        return `<button type="button" class="action-member-step${selected}" data-action-member-step="${escHtml(stepId)}"><span class="member-step-no">#${escHtml(stepId)}</span><span class="member-step-summary">${escHtml(summaryForActionStep(stepId))}</span></button>`;
      }).join('')}</div>`
    : '';
  const replayBody = artifacts ? renderActionArtifacts(artifacts) : '';

  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title';
    sideStepTitle.textContent = latestStepId != null ? `Action step #${latestStepId}` : representative;
  }
  if (sideReplay) {
    sideReplay.innerHTML = replayBody || '<div class="side-empty">no screenshot available.</div>';
  }
  renderSimpleActionDetails(calls);
  if (sideSelection) {
    sideSelection.innerHTML = (rows.length ? rows.join('') : '<div class="side-empty">no info.</div>') +
      memberList;
    if (typeof renderRightPanelAuxiliarySections === 'function') {
      renderRightPanelAuxiliarySections(inference, artifacts);
    }
    sideSelection.querySelectorAll('[data-action-member-step]').forEach(button => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        const stepId = button.getAttribute('data-action-member-step');
        if (selectedTimelineStepId === stepId) selectedTimelineStepId = null;
        selectTimelineActionStep(stepId);
      });
    });
  }
}

window.renderActionStepAdditionalInfo = renderActionStepAdditionalInfo;
window.renderActionGroupAdditionalInfo = renderActionGroupAdditionalInfo;

function renderTimelineActionStepInfo(stepId) {
  return renderActionStepAdditionalInfo(stepId);
}

function refreshAdditionalInfoForStep(stepId) {
  const key = stepKey(stepId);
  if (key == null || selectedTimelineStepId !== key) return;
  renderActionStepAdditionalInfo(selectedTimelineStepId);
}

function selectTimelineActionStep(stepId) {
  const key = stepKey(stepId);
  if (key == null) return;
  if (selectedTimelineStepId === key) {
    if (typeof clearGraphSelection === 'function') clearGraphSelection();
    highlightTimelineActionStep(null);
    renderActionStepAdditionalInfo(selectedTimelineStepId);
    return;
  }
  highlightTimelineActionStep(key);
  if (typeof selectGraphActionForStep === 'function') selectGraphActionForStep(key);
  renderActionStepAdditionalInfo(selectedTimelineStepId);
}

function addRow(cls, html) {
  clearEmpty();
  const el = document.createElement('div');
  el.className = `row ${cls || ''}`;
  el.innerHTML = html;
  appendTimelineElement(el);
  return el;
}

function addSpeaker(name, model) {
  clearEmpty();
  const el = document.createElement('div');
  el.className = `speaker ${name === 'user' ? 'user-speaker' : 'agent-speaker'}`;
  el.innerHTML =
    `<span class="marker"></span>` +
    `<span class="name">${escHtml(name)}</span>` +
    (model ? `<span class="sep">·</span><span class="model">${escHtml(model)}</span>` : '');
  appendTimelineElement(el);
}

function addBlock(cls, html) {
  clearEmpty();
  const el = document.createElement('div');
  el.className = `block ${cls || ''}`;
  el.innerHTML = html;
  appendTimelineElement(el);
  return el;
}

// ── Sidebar helpers ────────────────────────────────────
function resetSidebar() {
  subgoals = [];
  subgoalStartRowsById = new Map();
  pendingReplanFailedSubgoalId = null;
  actionSummariesByStep = new Map();
  actionSummaryCardsByStep = new Map();
  reasoningByStep = new Map();
  functionCallsByStep = new Map();
  observedUrlsByStep = new Map();
  actionShotsByStep = new Map();
  artifactsByStep = new Map();
  llmInferencesByStep = new Map();
  actionExecutionsByStep = new Map();
  pendingAgentFinalMessage = null;
  currentTimelineStepId = null;
  currentTimelineStepGroup = null;
  highlightTimelineActionStep(null);
  renderEmptyAdditionalInfo();
  sideTask.className = 'side-empty';
  sideTask.textContent = 'no active task.';
  renderPlan();
  resetGraph();
  metaStep.textContent = '—';
  metaUrl.textContent  = '—';
}

function storeLlmInference(ev) {
  if (!ev || ev.step_id == null) return;
  llmInferencesByStep.set(String(ev.step_id), {
    stepId: ev.step_id,
    tracePath: ev.llm_trace_path || null,
    rawContextOmitted: !!ev.raw_context_omitted,
    rawResponseOmitted: !!ev.raw_response_omitted,
    rawContext: ev.raw_context || null,
    rawResponse: ev.raw_response || null,
  });
  refreshActionSummaryForStep(ev.step_id);
}

function getLlmInferenceForStep(stepId) {
  if (stepId == null) return null;
  return llmInferencesByStep.get(String(stepId)) || null;
}

window.getLlmInferenceForStep = getLlmInferenceForStep;
