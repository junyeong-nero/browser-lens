// ── Stats helpers ──────────────────────────────────────
const OBSERVATION_TOOLS = new Set([
  'observe_page',
  'check_by_ref',
  'list_tabs',
  'get_accessibility_tree',
]);
const RECOVERY_TOOLS = new Set([
  'go_back',
  'go_forward',
  'reload_page',
  'list_tabs',
  'switch_to_next_tab',
  'switch_to_previous_tab',
  'switch_to_tab',
  'close_current_tab',
]);
const WAIT_TOOLS = new Set([
  'wait_5_seconds',
  'wait_for_ref',
]);
const NAVIGATION_TOOLS = new Set([
  'open_web_browser',
  'navigate',
  'search',
  'go_back',
  'go_forward',
  'reload_page',
  'switch_to_next_tab',
  'switch_to_previous_tab',
  'switch_to_tab',
  'close_current_tab',
]);
const STATS_SIGNATURE_IGNORED_ARG_KEYS = new Set([
  'ref_name',
]);
const STATS_TOOL_COLORWAY = [
  'var(--tds-fill-brand)',
  'var(--tds-fill-success)',
  'var(--tds-fill-warning)',
  'var(--tds-fill-danger)',
  'var(--tds-grey-900)',
  'color-mix(in srgb, var(--tds-fill-brand) 74%, var(--tds-fill-success))',
  'color-mix(in srgb, var(--tds-fill-brand) 70%, var(--tds-fill-warning))',
  'color-mix(in srgb, var(--tds-fill-success) 74%, var(--tds-fill-warning))',
  'color-mix(in srgb, var(--tds-fill-danger) 76%, var(--tds-fill-warning))',
  'color-mix(in srgb, var(--tds-fill-brand) 68%, var(--tds-grey-900))',
  'color-mix(in srgb, var(--tds-fill-success) 62%, var(--tds-grey-900))',
  'color-mix(in srgb, var(--tds-fill-warning) 70%, var(--tds-grey-900))',
  'color-mix(in srgb, var(--tds-fill-danger) 68%, var(--tds-grey-900))',
  'color-mix(in srgb, var(--tds-fill-brand) 84%, var(--tds-white))',
  'color-mix(in srgb, var(--tds-fill-success) 84%, var(--tds-white))',
  'color-mix(in srgb, var(--tds-fill-warning) 82%, var(--tds-white))',
  'color-mix(in srgb, var(--tds-fill-danger) 82%, var(--tds-white))',
  'color-mix(in srgb, var(--tds-grey-900) 74%, var(--tds-fill-brand))',
  'color-mix(in srgb, var(--tds-grey-900) 68%, var(--tds-fill-success))',
  'color-mix(in srgb, var(--tds-grey-900) 64%, var(--tds-fill-warning))',
  'color-mix(in srgb, var(--tds-grey-900) 64%, var(--tds-fill-danger))',
  'color-mix(in srgb, var(--tds-fill-brand) 56%, var(--tds-fill-danger))',
  'color-mix(in srgb, var(--tds-fill-success) 58%, var(--tds-fill-danger))',
  'color-mix(in srgb, var(--tds-fill-warning) 54%, var(--tds-fill-brand))',
];
const STATS_BEHAVIOR_COLORWAY = {
  observation: 'var(--tds-grey-700)',
  interaction: 'var(--tds-fill-brand)',
  navigation: 'var(--tds-fill-success)',
  recovery: 'var(--tds-fill-warning)',
  waiting: 'var(--tds-fill-danger)',
};
const STATS_FALLBACK_MIX_STRENGTHS = [88, 76, 64, 52];

function stableStatsValue(value) {
  if (Array.isArray(value)) return value.map(stableStatsValue);
  if (value && typeof value === 'object') {
    return Object.keys(value).sort().reduce((acc, key) => {
      if (STATS_SIGNATURE_IGNORED_ARG_KEYS.has(key)) return acc;
      acc[key] = stableStatsValue(value[key]);
      return acc;
    }, {});
  }
  return value;
}

function actionSignatureForStats(name, args) {
  return `${name || '<missing>'}|${JSON.stringify(stableStatsValue(args || {}))}`;
}

function toolBehaviorCategory(name) {
  if (OBSERVATION_TOOLS.has(name)) return 'observation';
  if (RECOVERY_TOOLS.has(name)) return 'recovery';
  if (WAIT_TOOLS.has(name)) return 'waiting';
  if (NAVIGATION_TOOLS.has(name)) return 'navigation';
  return 'interaction';
}

function collectStatsCalls() {
  const calls = [];
  functionCallsByStep.forEach((stepCalls, stepId) => {
    (Array.isArray(stepCalls) ? stepCalls : []).forEach((call, index) => {
      if (!call) return;
      const name = call.name || call.tool || '<missing>';
      const args = call.args && typeof call.args === 'object' ? call.args : {};
      calls.push({
        stepId: String(stepId),
        index,
        name,
        args,
        signature: actionSignatureForStats(name, args),
      });
    });
  });
  return calls.sort((a, b) => {
    const stepDelta = (Number(a.stepId) || 0) - (Number(b.stepId) || 0);
    return stepDelta || a.index - b.index;
  });
}

function collectStatsExecutions() {
  const executions = [];
  actionExecutionsByStep.forEach((stepExecutions, stepId) => {
    (Array.isArray(stepExecutions) ? stepExecutions : []).forEach((execution, index) => {
      if (!execution) return;
      executions.push({ ...execution, stepId: String(stepId), index });
    });
  });
  return executions.sort((a, b) => {
    const stepDelta = (Number(a.stepId) || 0) - (Number(b.stepId) || 0);
    return stepDelta || a.index - b.index;
  });
}

function isStatsExecutionError(execution) {
  const response = execution && execution.response;
  if (!response || typeof response !== 'object') return false;
  const status = String(response.status || '').toLowerCase();
  return status === 'error' || status === 'reobserve_required' || !!response.error_type;
}

function summarizeToolOutcomes(calls, executions) {
  const byTool = new Map();
  const executionQueues = new Map();

  executions.forEach(execution => {
    const key = `${execution.stepId}|${execution.signature}`;
    const queue = executionQueues.get(key) || [];
    queue.push(execution);
    executionQueues.set(key, queue);
  });

  function rowForTool(name) {
    const key = name || '<missing>';
    const row = byTool.get(key) || {
      label: key,
      count: 0,
      executedCount: 0,
      successCount: 0,
      errorCount: 0,
      skippedCount: 0,
    };
    byTool.set(key, row);
    return row;
  }

  let executedCount = 0;
  let successCount = 0;
  let errorCount = 0;
  let skippedCount = 0;

  calls.forEach(call => {
    const row = rowForTool(call.name);
    row.count += 1;
    const key = `${call.stepId}|${call.signature}`;
    const queue = executionQueues.get(key) || [];
    const execution = queue.shift() || null;
    if (!execution) {
      row.skippedCount += 1;
      skippedCount += 1;
      return;
    }
    row.executedCount += 1;
    executedCount += 1;
    if (isStatsExecutionError(execution)) {
      row.errorCount += 1;
      errorCount += 1;
      return;
    }
    row.successCount += 1;
    successCount += 1;
  });

  const toolRows = Array.from(byTool.values())
    .map(row => ({
      ...row,
      successRate: row.count ? row.successCount / row.count : 0,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  return {
    executedCount,
    successCount,
    errorCount,
    skippedCount,
    successRate: calls.length ? successCount / calls.length : 0,
    toolRows,
  };
}

function summarizeRepeatedActions(calls) {
  const bySignature = new Map();
  calls.forEach(call => {
    const row = bySignature.get(call.signature) || {
      signature: call.signature,
      name: call.name,
      args: call.args,
      count: 0,
      steps: [],
    };
    row.count += 1;
    row.steps.push(call.stepId);
    bySignature.set(call.signature, row);
  });
  const repeated = Array.from(bySignature.values())
    .filter(row => row.count > 1)
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const extraCount = repeated.reduce((total, row) => total + row.count - 1, 0);
  return {
    signatureCount: repeated.length,
    extraCount,
    top: repeated[0] || null,
  };
}

function collectStatsErrors() {
  let count = 0;
  stepErrorsByStep.forEach(messages => { count += Array.isArray(messages) ? messages.length : 0; });
  return { count, stepCount: stepErrorsByStep.size };
}

function computeStatsCueCounts() {
  const counts = { cycle: 0, repeated: 0, noop: 0 };
  if (typeof buildCueContext !== 'function') return counts;
  try {
    const context = buildCueContext();
    const maps = [];
    if (typeof trajectoryNodes !== 'undefined') maps.push(trajectoryNodes);
    if (typeof trajectoryViewports !== 'undefined') maps.push(trajectoryViewports);
    if (typeof trajectoryActions !== 'undefined') maps.push(trajectoryActions);
    maps.forEach(map => {
      map.forEach(node => {
        const cues = context.ownCuesById.get(node.id);
        if (!cues) return;
        if (cues.cycle) counts.cycle += 1;
        if (cues.repeated) counts.repeated += 1;
        if (cues.noop) counts.noop += 1;
      });
    });
  } catch (_) {}
  return counts;
}

function computeRevisitStats() {
  const result = {
    urlCount: 0,
    viewportCount: 0,
    topUrlLabel: 'none',
    topUrlVisits: 0,
  };
  try {
    const urls = typeof trajectoryNodes !== 'undefined'
      ? Array.from(trajectoryNodes.values())
      : [];
    const viewports = typeof trajectoryViewports !== 'undefined'
      ? Array.from(trajectoryViewports.values())
      : [];
    const revisitedUrls = urls.filter(node => (node.visits || 0) > 1);
    const revisitedViewports = viewports.filter(node => (node.visits || 0) > 1);
    result.urlCount = revisitedUrls.length;
    result.viewportCount = revisitedViewports.length;
    const topUrl = revisitedUrls.sort((a, b) => (b.visits || 0) - (a.visits || 0))[0];
    if (topUrl) {
      result.topUrlLabel = typeof trajectoryLabelFor === 'function'
        ? trajectoryLabelFor(topUrl)
        : (topUrl.host || topUrl.id);
      result.topUrlVisits = topUrl.visits || 0;
    }
  } catch (_) {}
  return result;
}

function buildStatsSnapshot() {
  const calls = collectStatsCalls();
  const executions = collectStatsExecutions();
  const behavior = new Map([
    ['observation', 0],
    ['interaction', 0],
    ['navigation', 0],
    ['recovery', 0],
    ['waiting', 0],
  ]);
  let observationCalls = 0;
  let recoveryCalls = 0;
  let waitCalls = 0;
  let navigationChurnCalls = 0;

  calls.forEach(call => {
    const category = toolBehaviorCategory(call.name);
    behavior.set(category, (behavior.get(category) || 0) + 1);
    if (OBSERVATION_TOOLS.has(call.name)) observationCalls += 1;
    if (RECOVERY_TOOLS.has(call.name)) recoveryCalls += 1;
    if (WAIT_TOOLS.has(call.name)) waitCalls += 1;
    if (NAVIGATION_TOOLS.has(call.name) || RECOVERY_TOOLS.has(call.name)) navigationChurnCalls += 1;
  });

  const totalToolCalls = calls.length;
  const outcomes = summarizeToolOutcomes(calls, executions);
  const toolRows = outcomes.toolRows;
  const behaviorRows = Array.from(behavior.entries())
    .map(([label, count]) => ({ label, count }))
    .filter(row => row.count > 0);
  const errors = collectStatsErrors();
  const repeated = summarizeRepeatedActions(calls);
  const cueCounts = computeStatsCueCounts();
  const revisits = computeRevisitStats();

  return {
    calls,
    totalToolCalls,
    uniqueTools: toolRows.length,
    toolRows,
    behaviorRows,
    executedToolCalls: outcomes.executedCount,
    successfulToolCalls: outcomes.successCount,
    failedToolCalls: outcomes.errorCount,
    skippedToolCalls: outcomes.skippedCount,
    toolSuccessRate: outcomes.successRate,
    observationCalls,
    stateChangingCalls: Math.max(0, totalToolCalls - observationCalls),
    recoveryCalls,
    waitCalls,
    navigationChurnCalls,
    errorCount: errors.count,
    errorStepCount: errors.stepCount,
    repeated,
    cueCounts,
    revisits,
  };
}
