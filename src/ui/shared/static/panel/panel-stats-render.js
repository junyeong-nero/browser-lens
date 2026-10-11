function statsPercent(count, total) {
  if (!total) return '0%';
  return `${Math.round((count / total) * 100)}%`;
}

function renderStatCard(label, value, note = '') {
  return `
    <div class="stat-card">
      <div class="stat-label">${escHtml(label)}</div>
      <div class="stat-value">${escHtml(value)}</div>
      <div class="stat-note">${escHtml(note)}</div>
    </div>`;
}

function statsChartValue(row, total) {
  const share = statsPercent(row.count, total);
  if (row.successCount != null) {
    return `${row.count} calls · ${row.successCount}/${row.count} ok · ${share}`;
  }
  return `${row.count} · ${share}`;
}

function statsChartTooltip(row, total) {
  const share = statsPercent(row.count, total);
  const parts = [`${row.label}: ${row.count} calls`, `${share} of total`];
  if (row.successCount != null) {
    parts.push(`${row.successCount}/${row.count} successful`);
  }
  if (row.skippedCount) parts.push(`${row.skippedCount} skipped`);
  if (row.errorCount) parts.push(`${row.errorCount} failed`);
  return parts.join(' · ');
}

function statsFallbackColor(index, hueOffset = 0) {
  const safeIndex = Math.max(0, Math.abs(Number(index) || 0));
  const offset = Math.max(0, Math.abs(Math.round(Number(hueOffset) || 0)));
  const base = STATS_TOOL_COLORWAY[(safeIndex + offset) % STATS_TOOL_COLORWAY.length];
  const strength = STATS_FALLBACK_MIX_STRENGTHS[safeIndex % STATS_FALLBACK_MIX_STRENGTHS.length];
  const target = safeIndex % 2 === 0 ? 'var(--tds-white)' : 'var(--tds-grey-900)';
  return `color-mix(in srgb, ${base} ${strength}%, ${target})`;
}

function statsChartColor(row, index, colorway = 'tool') {
  if (colorway === 'behavior') {
    return STATS_BEHAVIOR_COLORWAY[row.label] || statsFallbackColor(index, 61);
  }
  return STATS_TOOL_COLORWAY[index] || statsFallbackColor(index - STATS_TOOL_COLORWAY.length, 19);
}

function positionStatsTooltip(container, tooltip, event, target = null) {
  const rect = container.getBoundingClientRect();
  let x = event && Number.isFinite(event.clientX) ? event.clientX - rect.left : rect.width / 2;
  let y = event && Number.isFinite(event.clientY) ? event.clientY - rect.top : rect.height / 2;
  if (target && (!event || !Number.isFinite(event.clientX) || !Number.isFinite(event.clientY))) {
    const targetRect = target.getBoundingClientRect();
    x = targetRect.left + targetRect.width / 2 - rect.left;
    y = targetRect.top - rect.top;
  }
  x = Math.max(12, Math.min(rect.width - 12, x));
  y = Math.max(18, Math.min(rect.height - 8, y));
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}

function attachStatsChartHover(container) {
  const tooltip = container.querySelector('.stats-chart-tooltip');
  if (!tooltip) return;
  container.querySelectorAll('[data-stats-tooltip]').forEach(target => {
    const show = event => {
      tooltip.textContent = target.dataset.statsTooltip || '';
      tooltip.hidden = false;
      positionStatsTooltip(container, tooltip, event, target);
    };
    const move = event => {
      if (tooltip.hidden) return;
      positionStatsTooltip(container, tooltip, event, target);
    };
    const hide = () => {
      tooltip.hidden = true;
      tooltip.textContent = '';
    };
    target.addEventListener('mouseenter', show);
    target.addEventListener('mousemove', move);
    target.addEventListener('mouseleave', hide);
    target.addEventListener('focus', show);
    target.addEventListener('blur', hide);
  });
}

function renderStatsCircularChart(container, rows, total, caption = 'calls', colorway = 'tool') {
  if (!container) return;
  const visibleRows = rows.filter(row => row.count > 0);
  if (!visibleRows.length || !total) {
    container.innerHTML = '<div class="side-empty">no data.</div>';
    return;
  }
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const gap = visibleRows.length > 1 ? 1.4 : 0;
  let offset = 0;
  const segments = visibleRows.map((row, index) => {
    const share = row.count / total;
    const color = statsChartColor(row, index, colorway);
    const dash = Math.max(0, (share * circumference) - gap);
    const segmentOffset = -offset;
    offset += share * circumference;
    const tooltip = statsChartTooltip(row, total);
    return {
      row,
      color,
      dash,
      offset: segmentOffset,
      tooltip,
      value: statsChartValue(row, total),
    };
  });
  const segmentMarkup = segments.map(segment => `
    <circle
      class="stats-donut-segment"
      cx="50"
      cy="50"
      r="${radius}"
      style="--stats-segment-color:${segment.color}"
      stroke-dasharray="${segment.dash.toFixed(2)} ${circumference.toFixed(2)}"
      stroke-dashoffset="${segment.offset.toFixed(2)}"
      transform="rotate(-90 50 50)"
      tabindex="0"
      role="img"
      aria-label="${escHtml(segment.tooltip)}"
      data-stats-tooltip="${escHtml(segment.tooltip)}"></circle>`).join('');
  const legendMarkup = segments.map(segment => `
    <div
      class="stats-chart-legend-row"
      tabindex="0"
      style="--stats-segment-color:${segment.color}"
      data-stats-tooltip="${escHtml(segment.tooltip)}">
      <span class="stats-chart-swatch" aria-hidden="true"></span>
      <span class="stats-chart-label">${escHtml(segment.row.label)}</span>
      <span class="stats-chart-value">${escHtml(segment.value)}</span>
    </div>`).join('');
  container.innerHTML = `
    <div class="stats-donut-wrap">
      <svg class="stats-donut" viewBox="0 0 100 100">
        <circle class="stats-donut-bg" cx="50" cy="50" r="${radius}"></circle>
        ${segmentMarkup}
      </svg>
      <div class="stats-donut-center">
        <div class="stats-donut-total">${escHtml(total)}</div>
        <div class="stats-donut-caption">${escHtml(caption)}</div>
      </div>
    </div>
    <div class="stats-chart-legend">${legendMarkup}</div>
    <div class="stats-chart-tooltip" role="tooltip" hidden></div>`;
  attachStatsChartHover(container);
}

function renderStatsOverview(snapshot) {
  if (!statsOverview) return;
  const cueHits = snapshot.cueCounts.cycle + snapshot.cueCounts.noop;
  statsOverview.innerHTML = [
    renderStatCard('Tool calls', snapshot.totalToolCalls, `${snapshot.calls.length} recorded calls`),
    renderStatCard('Tool success', statsPercent(snapshot.successfulToolCalls, snapshot.totalToolCalls), `${snapshot.successfulToolCalls}/${snapshot.totalToolCalls} calls`),
    renderStatCard('Unique tools', snapshot.uniqueTools, snapshot.toolRows[0] ? `top: ${snapshot.toolRows[0].label}` : 'top: none'),
    renderStatCard('State-changing', snapshot.stateChangingCalls, `${statsPercent(snapshot.stateChangingCalls, snapshot.totalToolCalls)} of calls`),
    renderStatCard('Errors', snapshot.errorCount, `${snapshot.errorStepCount} affected steps`),
    renderStatCard('Repeated calls', snapshot.repeated.extraCount, `${snapshot.repeated.signatureCount} repeated signatures`),
    renderStatCard('Cue hits', cueHits, `${snapshot.cueCounts.cycle} loop / ${snapshot.cueCounts.noop} no-op`),
  ].join('');
}

function renderStatsDiagnostics(snapshot) {
  if (!statsDiagnostics) return;
  const actionCalls = Math.max(0, snapshot.totalToolCalls - snapshot.observationCalls);
  const topRepeated = snapshot.repeated.top
    ? `${snapshot.repeated.top.name} at steps ${snapshot.repeated.top.steps.slice(0, 4).map(step => `#${step}`).join(', ')}`
    : 'none';
  const topRevisit = snapshot.revisits.topUrlVisits
    ? `${snapshot.revisits.topUrlLabel} (${snapshot.revisits.topUrlVisits} visits)`
    : 'none';
  const rows = [
    {
      label: 'Observation-to-action',
      value: `${snapshot.observationCalls}:${actionCalls}`,
      detail: `${statsPercent(snapshot.observationCalls, snapshot.totalToolCalls)} observation calls`,
    },
    {
      label: 'Navigation churn',
      value: snapshot.navigationChurnCalls,
      detail: `${statsPercent(snapshot.navigationChurnCalls, snapshot.totalToolCalls)} navigation/recovery calls`,
    },
    {
      label: 'Recovery actions',
      value: snapshot.recoveryCalls,
      detail: 'back, reload, tab switch, and tab close calls',
    },
    {
      label: 'Wait / idle cost',
      value: snapshot.waitCalls,
      detail: `${statsPercent(snapshot.waitCalls, snapshot.totalToolCalls)} wait-oriented calls`,
    },
    {
      label: 'Skipped calls',
      value: snapshot.skippedToolCalls,
      detail: 'declared by the model but not executed',
    },
    {
      label: 'Failed executions',
      value: snapshot.failedToolCalls,
      detail: 'executed tool calls with error responses',
    },
    {
      label: 'Ineffective executions',
      value: snapshot.cueCounts.noop,
      detail: 'executed actions currently flagged as no-op',
    },
    {
      label: 'Repeated actions',
      value: snapshot.repeated.extraCount,
      detail: topRepeated,
    },
    {
      label: 'Cue summary',
      value: snapshot.cueCounts.cycle + snapshot.cueCounts.noop + snapshot.cueCounts.repeated,
      detail: `${snapshot.cueCounts.cycle} loop, ${snapshot.cueCounts.noop} no-op, ${snapshot.cueCounts.repeated} repeated`,
    },
    {
      label: 'Revisit pressure',
      value: snapshot.revisits.urlCount + snapshot.revisits.viewportCount,
      detail: `${snapshot.revisits.urlCount} URLs, ${snapshot.revisits.viewportCount} viewports; top ${topRevisit}`,
    },
    {
      label: 'Error steps',
      value: snapshot.errorStepCount,
      detail: `${snapshot.errorCount} emitted step errors`,
    },
  ];
  statsDiagnostics.innerHTML = rows.map(row => `
    <div class="stats-diagnostic">
      <span class="stats-diagnostic-label">${escHtml(row.label)}</span>
      <span class="stats-diagnostic-value">${escHtml(row.value)}</span>
      <span class="stats-diagnostic-detail">${escHtml(row.detail)}</span>
    </div>`).join('');
}

function renderStats() {
  if (!statsEmpty || !statsContent) return;
  const snapshot = buildStatsSnapshot();
  const hasData = snapshot.totalToolCalls > 0 || snapshot.errorCount > 0;
  statsEmpty.hidden = hasData;
  statsContent.hidden = !hasData;
  if (!hasData) {
    if (statsOverview) statsOverview.innerHTML = '';
    if (statsToolChart) statsToolChart.innerHTML = '';
    if (statsBehaviorChart) statsBehaviorChart.innerHTML = '';
    if (statsDiagnostics) statsDiagnostics.innerHTML = '';
    return;
  }
  renderStatsOverview(snapshot);
  renderStatsCircularChart(statsToolChart, snapshot.toolRows, snapshot.totalToolCalls, 'tool calls', 'tool');
  renderStatsCircularChart(statsBehaviorChart, snapshot.behaviorRows, snapshot.totalToolCalls, 'behavior', 'behavior');
  renderStatsDiagnostics(snapshot);
}

function isStatsViewActive() {
  return document.body.classList.contains('view-stats');
}

function updateStats({ force = false } = {}) {
  if (!force && !isStatsViewActive()) {
    statsRenderDirty = true;
    return;
  }
  statsRenderDirty = false;
  renderStats();
}

function resetStats() {
  stepErrorsByStep = new Map();
  statsRenderDirty = false;
  renderStats();
}

function openStatsHelp() {
  if (!statsHelpPanel) return;
  statsHelpPreviousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  statsHelpPanel.hidden = false;
  requestAnimationFrame(() => {
    if (statsHelpClose) statsHelpClose.focus();
    else if (statsHelpCard) statsHelpCard.focus();
  });
}

function closeStatsHelp() {
  if (!statsHelpPanel || statsHelpPanel.hidden) return;
  statsHelpPanel.hidden = true;
  if (statsHelpPreviousFocus && typeof statsHelpPreviousFocus.focus === 'function') {
    statsHelpPreviousFocus.focus();
  }
  statsHelpPreviousFocus = null;
}

function recordStepError(stepId, message) {
  const key = stepKey(stepId) || 'unknown';
  const messages = stepErrorsByStep.get(key) || [];
  messages.push(message || 'unknown error');
  stepErrorsByStep.set(key, messages);
  updateStats();
}

window.updateStats = updateStats;
