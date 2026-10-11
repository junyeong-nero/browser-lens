// ── graph tooltip helpers ────────────────────────────────
function graphTooltipHtml(d) {
  const rows = [];
  const title = d.label || d.host || d.actionName || d.id;
  rows.push(`<div class="tt-row"><span>level</span><span class="v">${escHtml(d.type || '—')}</span></div>`);
  if (d.isStart && d.isEnd) rows.push(`<div class="tt-row"><span>flow</span><span class="v">start & end</span></div>`);
  else if (d.isStart) rows.push(`<div class="tt-row"><span>flow</span><span class="v">start ▶</span></div>`);
  else if (d.isEnd) rows.push(`<div class="tt-row"><span>flow</span><span class="v">end ■</span></div>`);
  if (d.actionStepCount != null) rows.push(`<div class="tt-row"><span>total steps</span><span class="v">${d.actionStepCount}</span></div>`);
  if (d.actionCount != null) rows.push(`<div class="tt-row"><span>unique actions</span><span class="v">${d.actionCount}</span></div>`);
  if (d.visits != null) rows.push(`<div class="tt-row"><span>visits</span><span class="v">${d.visits}</span></div>`);
  if (d.drillable) rows.push(`<div class="tt-row"><span>double-click</span><span class="v">drill in</span></div>`);
  const cueRows = [];
  if (d && d.ownCues) {
    const own = d.ownCues;
    const inside = d.rollupBreakdown || { cycle: 0, repeated: 0, noop: 0 };
    const visibleCueTypes = typeof BADGE_CUE_TYPES !== 'undefined' ? BADGE_CUE_TYPES : ['cycle', 'repeated', 'noop'];
    const cueLabels = { cycle: 'cycle', repeated: 'repeated', noop: 'no-op' };
    for (const cueType of visibleCueTypes) {
      const ownN = own[cueType] ? 1 : 0;
      const insideN = inside[cueType] || 0;
      if (ownN || insideN) {
        cueRows.push(`<div class="tt-row"><span>${cueLabels[cueType]}</span><span class="v">${ownN} own / ${insideN} inside</span></div>`);
      }
    }
  }
  const cueSection = cueRows.length
    ? `<div class="tt-section">Cues</div>` + cueRows.join('')
    : '';
  return `<div class="tt-url">${escHtml(title)}</div>` + rows.join('') + cueSection;
}

function positionGraphTooltip(tooltip, wrapEl, event) {
  const rect = wrapEl.getBoundingClientRect();
  const x = event.clientX - rect.left + 14;
  const y = event.clientY - rect.top + 14;
  const maxX = rect.width - tooltip.offsetWidth - 10;
  const maxY = rect.height - tooltip.offsetHeight - 10;
  tooltip.style.left = Math.max(6, Math.min(x, maxX)) + 'px';
  tooltip.style.top = Math.max(6, Math.min(y, maxY)) + 'px';
}
