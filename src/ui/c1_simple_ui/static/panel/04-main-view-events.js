function setMainView(view) {
  document.body.classList.toggle('view-timeline', view === 'timeline');
  document.body.classList.toggle('view-graph', view === 'graph');
}
function activateMainView(view, options = {}) {
  const scrollSelection = options.scrollSelection !== false;
  const tabs = document.querySelectorAll('.view-tab');
  const panes = document.querySelectorAll('.view-pane');
  tabs.forEach(t => { t.classList.toggle('active', t.dataset.view === view); });
  panes.forEach(p => { p.classList.toggle('active', p.dataset.view === view); });
  setMainView(view);
  if (view === 'graph') {
    resizeGraph();
    updateGraph({ force: true });
  } else if (view === 'timeline' && scrollSelection) {
    scrollHighlightedTimelineStep();
  }
}
(function setupTabs() {
  const tabs = document.querySelectorAll('.view-tab');
  setMainView('timeline');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      activateMainView(tab.dataset.view);
    });
  });
})();

// ── Event handlers ─────────────────────────────────────
function handleEvent(ev) {
  switch (ev.type) {

    case 'session_ready':
      setStatus('connected', 'ready');
      setInputEnabled(true);
      setAgentModel(ev.model_name);
      break;

    case 'task_started':
      isRunning = true;
      isSubmitting = false;
      isStopping = false;
      pendingAgentFinalMessage = null;
      liveSessionId = ev.session_id || null;
      setStatus('running', 'running');
      setInputEnabled(false);
      resetSidebar();
      setSideTask(ev.query);
      addSpeaker('user', null);
      addRow('user-message', escHtml(ev.query));
      addSpeaker('browser-agent', null);
      break;

    case 'planner_started':
      setStatus('running', 'planning');
      break;

    case 'planner_completed': {
      const items = ev.subgoals || [];
      setSubgoals(items);
      setStatus('running', 'running');
      break;
    }

    case 'planner_replanning':
      pendingReplanFailedSubgoalId = ev.failed_subgoal_id;
      setStatus('running', 'planning');
      break;

    case 'planner_replanned': {
      const items = ev.subgoals || [];
      replaceSubgoalsAfterFailed(
        ev.failed_subgoal_id != null ? ev.failed_subgoal_id : pendingReplanFailedSubgoalId,
        items
      );
      pendingReplanFailedSubgoalId = null;
      setStatus('running', 'running');
      break;
    }

    case 'subgoal_started':
      updateSubgoalStatus(ev.subgoal_id, 'active');
      recordSubgoalStart(
        ev.subgoal_id,
        addRow('', `<span style="color:var(--orange)">▸</span> subgoal ${escHtml(ev.subgoal_id)} <span class="pill running">RUNNING</span> <span class="dim" style="color:var(--fg-dim)">${escHtml(ev.description || '')}</span>`)
      );
      break;

    case 'subgoal_completed':
      updateSubgoalStatus(ev.subgoal_id, 'done');
      addRow('ok', `✓ subgoal ${escHtml(ev.subgoal_id)} <span class="pill done">DONE</span>`);
      break;

    case 'subgoal_failed':
      updateSubgoalStatus(ev.subgoal_id, 'failed');
      addRow('err', `✗ subgoal ${escHtml(ev.subgoal_id)} <span class="pill failed">FAILED</span> ${escHtml(ev.reason || '')}`);
      break;

    case 'replan_error':
      addBlock('red', `<div class="title">replan error</div><div class="meta">${escHtml(ev.error_message || '')}</div>`);
      break;

    case 'step_started':
      metaStep.textContent = `#${ev.step_id}`;
      beginActionStepGroup(ev.step_id);
      break;

    case 'llm_inference':
      storeLlmInference(ev);
      break;

    case 'reasoning_extracted':
      if (ev.reasoning) {
        storeStepReasoning(ev.step_id, ev.reasoning);
      }
      break;

    case 'function_calls_extracted': {
      const calls = (ev.function_calls || []);
      if (!calls.length) break;
      storeFunctionCalls(ev.step_id, calls);
      break;
    }

    case 'review_metadata_extracted': {
      const what = ev.what || ev.action_summary;
      if (ev.final_result_summary) pendingAgentFinalMessage = ev.final_result_summary;
      if (!what) break;
      upsertActionSummary({
        step: ev.step_id,
        subgoalId: ev.subgoal_id != null ? ev.subgoal_id : null,
        phaseId: ev.phase_id || null,
        what,
        why: ev.why || ev.reason || '',
        reason: ev.reason || '',
        actionSummary: ev.action_summary || '',
        outcome: ev.outcome || '',
      });
      break;
    }

    case 'action_executed':
      if (ev.action && ev.action.name && !functionCallsByStep.has(stepKey(ev.step_id))) {
        storeFunctionCalls(ev.step_id, [ev.action]);
      }
      storeActionExecutionForStats(ev);
      if (ev.env_state && ev.env_state.url) {
        metaUrl.textContent = ev.env_state.url;
        storeObservedUrl(ev.step_id, ev.env_state.url);
        recordActionExecution(ev);
      }
      if (ev.artifacts) {
        storeArtifactsForStep(ev.step_id, ev.artifacts);
      }
      if (replayMode && replaySessionId && ev.artifacts && (ev.artifacts.after_screenshot_path || ev.artifacts.screenshot_path)) {
        const href = replayArtifactHref(ev.artifacts.after_screenshot_path || ev.artifacts.screenshot_path, 'history');
        storeActionShot(ev.step_id, href);
      }
      break;

    case 'step_error':
      addBlock('red', `<div class="title">error</div><div class="meta">${escHtml(ev.error_message || 'unknown error')}</div>`);
      finishActionStepGroup(ev.step_id);
      break;

    case 'model_request_retry':
      addRow('warn', `~ retry #${escHtml(ev.attempt)} in ${escHtml(ev.delay_seconds)}s`);
      break;

    case 'step_complete': {
      if (!pendingAgentFinalMessage && ev.final_reasoning) pendingAgentFinalMessage = ev.final_reasoning;
      finishActionStepGroup(ev.step_id);
      const key = stepKey(ev.step_id);
      const actions = actionExecutionsByStep.get(key);
      if (!actions || !actions.length) removeNonActionStep(ev.step_id);
      break;
    }

    case 'task_complete': {
      isRunning = false;
      isSubmitting = false;
      isStopping = false;
      clearGraphRunningStep();
      setStatus('connected', 'ready');
      setInputEnabled(true);
      subgoals.forEach(sg => { if (sg.status === 'active') sg.status = 'done'; });
      renderPlan();
      const finalMessage = pendingAgentFinalMessage || ev.final_reasoning || ev.summary;
      if (finalMessage) addRow('agent-message', renderMarkdownSafe(finalMessage));
      pendingAgentFinalMessage = null;
      break;
    }

    case 'task_failed': {
      isRunning = false;
      isSubmitting = false;
      isStopping = false;
      clearGraphRunningStep();
      setStatus('connected', 'ready');
      setInputEnabled(true);
      subgoals.forEach(sg => { if (sg.status === 'active') sg.status = 'failed'; });
      renderPlan();
      pendingAgentFinalMessage = null;
      const errorMessage = ev.error_message || 'unknown error';
      addRow('agent-message failed-message',
        `<div class="message-title">task failed</div>` +
        `<div class="message-meta">${renderMarkdownSafe(errorMessage)}</div>`
      );
      break;
    }

    case 'task_interrupted':
      isRunning = false;
      isSubmitting = false;
      isStopping = false;
      clearGraphRunningStep();
      setStatus('connected', 'ready');
      setInputEnabled(true);
      subgoals.forEach(sg => { if (sg.status === 'active') sg.status = 'failed'; });
      renderPlan();
      pendingAgentFinalMessage = null;
      addBlock('orange', `<div class="title">task interrupted</div><div class="meta">${escHtml(ev.reason || 'stopped by user')}</div>`);
      break;

    case 'session_closed':
      clearGraphRunningStep();
      setStatus('disconnected', 'session ended');
      setInputEnabled(false);
      addRow('dim', 'session closed.');
      break;
  }
}
