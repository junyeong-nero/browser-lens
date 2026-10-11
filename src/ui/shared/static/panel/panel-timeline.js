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

function renderEmptyAdditionalInfo(message = 'no action step selected.') {
  const empty = `<div class="side-empty">${escHtml(message)}</div>`;
  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title side-empty';
    sideStepTitle.textContent = message;
  }
  if (sideReplay) sideReplay.innerHTML = empty;
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
  const actionNode = typeof window.actionNodeForStep === 'function' ? window.actionNodeForStep(key) : null;
  const actionContext = actionNode || (calls.length ? { actionName: calls[0].name } : null);

  const rows = [
    renderAdditionalInfoRow('Action step number', `#${key}`),
    renderAdditionalInfoRow('Summary', what),
    renderAdditionalInfoRow('Outcome', item.outcome && item.outcome !== '—' ? item.outcome : '—'),
    renderAdditionalInfoRow('Reasoning', reasoning || '—'),
    renderAdditionalInfoRow('Function call', functionCallNames(calls)),
    renderAdditionalInfoRow('Function call arguments', functionCallArguments(calls)),
  ];
  if (url) rows.push(renderAdditionalInfoRow('Observed URL', url));

  const replayBody = artifacts ? renderActionArtifacts(artifacts, actionContext) : '';

  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title';
    sideStepTitle.textContent = `Step #${key}`;
  }
  if (sideReplay) {
    sideReplay.innerHTML = replayBody || '<div class="side-empty">no replay artifacts.</div>';
    if (typeof hydrateNoopEvidence === 'function') hydrateNoopEvidence(sideReplay);
  }
  if (sideSelection) {
    sideSelection.innerHTML = rows.length ? rows.join('') : '<div class="side-empty">no info.</div>';
  }
  if (typeof renderRightPanelAuxiliarySections === 'function') {
    renderRightPanelAuxiliarySections(inference, artifacts, actionNode);
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
  const replayBody = artifacts ? renderActionArtifacts(artifacts, actionNode) : '';

  if (sideStepTitle) {
    sideStepTitle.className = 'side-step-title';
    sideStepTitle.textContent = representative;
  }
  if (sideReplay) {
    sideReplay.innerHTML = replayBody || '<div class="side-empty">no replay artifacts.</div>';
    if (typeof hydrateNoopEvidence === 'function') hydrateNoopEvidence(sideReplay);
  }
  if (sideSelection) {
    sideSelection.innerHTML = (rows.length ? rows.join('') : '<div class="side-empty">no info.</div>') +
      memberList;
    if (typeof renderRightPanelAuxiliarySections === 'function') {
      renderRightPanelAuxiliarySections(inference, artifacts, actionNode);
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
