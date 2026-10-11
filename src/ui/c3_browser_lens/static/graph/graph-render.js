// ── d3 graph renderer ──────────────────────────────────
const graph = (() => {
  const svgEl = document.getElementById('graph-svg');
  const wrapEl = document.getElementById('graph-wrap');
  const emptyEl = document.getElementById('graph-empty');
  const breadcrumbEl = document.getElementById('graph-breadcrumb');
  const tooltip = document.getElementById('graph-tooltip');
  const legendEl = document.getElementById('graph-legend');
  const cueLegendEl = document.getElementById('graph-cue-legend');
  const fitBtn = document.getElementById('graph-fit');
  const zoomInBtn = document.getElementById('graph-zoom-in');
  const zoomOutBtn = document.getElementById('graph-zoom-out');

  const svg = d3.select(svgEl);
  const root = svg.append('g').attr('class', 'graph-root');
  const linkG = root.append('g').attr('class', 'links');
  const nodeG = root.append('g').attr('class', 'nodes');
  const GRAPH_WORK_COLOR_STOPS = [
    [0, 'var(--graph-work-color-low)'],
    [0.25, 'var(--graph-work-color-low-mid)'],
    [0.5, 'var(--graph-work-color-mid)'],
    [0.75, 'var(--graph-work-color-high-mid)'],
    [1, 'var(--graph-work-color-high)'],
  ];
  const zoomBehavior = d3.zoom()
    .scaleExtent([0.3, 3])
    .on('zoom', (event) => {
      root.attr('transform', event.transform);
    });

  svg.call(zoomBehavior);

  const simulation = d3.forceSimulation()
    .force('link', d3.forceLink().id(d => d.id).distance(90).strength(1).iterations(4))
    .force('charge', d3.forceManyBody().strength(-160).distanceMax(360))
    .force('center', d3.forceCenter(0, 0).strength(0.05))
    .force('collide', d3.forceCollide(34).strength(1).iterations(2))
    .on('tick', ticked);

  let nodeSel = nodeG.selectAll('g');
  let linkSel = linkG.selectAll('path');
  let nodesData = [];
  let linksData = [];
  let graphMode = 'url';

  function resize() {
    const { width, height } = wrapEl.getBoundingClientRect();
    svgEl.setAttribute('viewBox', `${-width / 2} ${-height / 2} ${width} ${height}`);
    svgEl.setAttribute('width', width);
    svgEl.setAttribute('height', height);
  }
  window.addEventListener('resize', resize);
  resize();

  function graphTransition() {
    return svg.transition().duration(220);
  }

  function zoomBy(factor) {
    graphTransition().call(zoomBehavior.scaleBy, factor);
  }

  function fitToNodes() {
    if (!nodesData.length) {
      graphTransition().call(zoomBehavior.transform, d3.zoomIdentity);
      return;
    }
    const { width, height } = wrapEl.getBoundingClientRect();
    if (!width || !height) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodesData.forEach(n => {
      const x = Number.isFinite(n.x) ? n.x : n._targetX;
      const y = Number.isFinite(n.y) ? n.y : n._targetY;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      const r = graphNodeRadius(n) + 8;
      if (x - r < minX) minX = x - r;
      if (x + r > maxX) maxX = x + r;
      if (y - r < minY) minY = y - r;
      if (y + r > maxY) maxY = y + r;
    });
    if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
      graphTransition().call(zoomBehavior.transform, d3.zoomIdentity);
      return;
    }
    const boundsWidth = Math.max(1, maxX - minX);
    const boundsHeight = Math.max(1, maxY - minY);
    const padding = 40;
    const scale = Math.max(
      0.3,
      Math.min(3, Math.min((width - padding) / boundsWidth, (height - padding) / boundsHeight))
    );
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const transform = d3.zoomIdentity
      .translate(-centerX * scale, -centerY * scale)
      .scale(scale);
    graphTransition().call(zoomBehavior.transform, transform);
  }

  if (fitBtn) fitBtn.addEventListener('click', (event) => { event.stopPropagation(); fitToNodes(); });
  if (zoomInBtn) zoomInBtn.addEventListener('click', (event) => { event.stopPropagation(); zoomBy(1.25); });
  if (zoomOutBtn) zoomOutBtn.addEventListener('click', (event) => { event.stopPropagation(); zoomBy(0.8); });

  function ticked() {
    linkSel.attr('d', d => graphLinkPath(d, graphNodeRadius));
    nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
  }

  function showTooltip(event, d) {
    tooltip.innerHTML = graphTooltipHtml(d);
    tooltip.classList.remove('hidden');
    moveTooltip(event);
  }

  function moveTooltip(event) {
    positionGraphTooltip(tooltip, wrapEl, event);
  }

  function hideTooltip() {
    tooltip.classList.add('hidden');
  }


  // Repeated node highlight (Table 2) encodes visit count — how often a state
  // was revisited. Reuse the cue layer's nodeVisitCount so node size/color and
  // the `repeated` cue are driven by the same magnitude.
  function graphNodeVisitCount(d) {
    if (!d) return 0;
    return nodeVisitCount(d.type, d);
  }

  function trajectoryMaxVisitCount() {
    let max = 0;
    const consider = node => {
      const count = graphNodeVisitCount(node);
      if (count > max) max = count;
    };
    trajectoryNodes.forEach(consider);
    trajectoryViewports.forEach(consider);
    trajectoryActions.forEach(consider);
    return max;
  }

  function graphNodeRadius(d) {
    const base = 7;
    const count = graphNodeVisitCount(d);
    return base + Math.min(9, Math.log2((count || 1) + 1) * 1.8);
  }

  function levelEndpointShape(d) {
    if (!d || (!d.isStart && !d.isEnd)) return '';
    const r = graphNodeRadius(d);
    if (d.isStart && d.isEnd) {
      const s = r * 1.25;
      return `M 0 ${-s} L ${s} 0 L 0 ${s} L ${-s} 0 Z`;
    }
    if (d.isStart) {
      const w = r * 1.35;
      const h = r * 1.15;
      return `M ${-w * 0.65} ${-h} L ${w} 0 L ${-w * 0.65} ${h} Z`;
    }
    const s = r * 1.05;
    return `M ${-s} ${-s} L ${s} ${-s} L ${s} ${s} L ${-s} ${s} Z`;
  }

  function graphWorkColor(t) {
    const clamped = Math.max(0, Math.min(1, Number(t) || 0));
    for (let i = 1; i < GRAPH_WORK_COLOR_STOPS.length; i += 1) {
      const [startT, startColor] = GRAPH_WORK_COLOR_STOPS[i - 1];
      const [endT, endColor] = GRAPH_WORK_COLOR_STOPS[i];
      if (clamped <= endT) {
        const startWeight = Math.round((1 - ((clamped - startT) / (endT - startT))) * 100);
        return `color-mix(in srgb, ${startColor} ${startWeight}%, ${endColor})`;
      }
    }
    return 'var(--graph-work-color-high)';
  }

  function graphNodeFill(d, maxVisitCount) {
    const count = graphNodeVisitCount(d);
    if (!count || !maxVisitCount) return 'var(--graph-work-color-low)';
    const minVisitCount = 1;
    const clampedMaxVisitCount = Math.max(minVisitCount, maxVisitCount);
    const clampedCount = Math.max(minVisitCount, Math.min(count, clampedMaxVisitCount));
    const normalized = Math.sqrt((clampedCount - minVisitCount) / Math.max(1, clampedMaxVisitCount - minVisitCount));
    return graphWorkColor(normalized);
  }

  function updateGraphLegend(maxVisitCount, hasNodes) {
    if (legendEl) {
      if (!hasNodes) legendEl.classList.add('hidden');
      else {
        const legendMinVisitCount = 1;
        const roundedMaxVisitCount = Math.max(legendMinVisitCount, Math.round(Number(maxVisitCount) || 0));
        const maxLabel = legendEl.querySelector('[data-legend-max]');
        if (maxLabel) maxLabel.textContent = `${roundedMaxVisitCount}`;
        legendEl.classList.remove('hidden');
      }
    }
    if (cueLegendEl) cueLegendEl.classList.toggle('hidden', !hasNodes);
  }

  function drag() {
    return d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        if (d.isRoot) {
          if (d._rootPin) {
            d.fx = d._rootPin.x;
            d.fy = d._rootPin.y;
          } else {
            d.fx = null;
            d.fy = null;
          }
          return;
        }
        d.fx = null; d.fy = null;
      });
  }

  function layerName(level) {
    if (level === 'action') return 'Action layer';
    if (level === 'viewport') return 'Viewport layer';
    return 'URL layer';
  }

  function renderBreadcrumb(payload) {
    const crumbs = (payload && payload.breadcrumb) || [];
    const parts = [];
    crumbs.forEach((crumb, idx) => {
      parts.push(`<button type="button" data-idx="${idx}">${escHtml(layerName(crumb.level))}</button>`);
      parts.push('<span class="sep">›</span>');
    });
    const parentLabel = payload && payload.parentLabel && payload.mode !== 'url' ? payload.parentLabel : null;
    parts.push(`<span class="current-layer">${escHtml(layerName(payload.mode))}</span>`);
    if (parentLabel) parts.push(`<span class="parent-label">inside ${escHtml(parentLabel)}</span>`);
    breadcrumbEl.innerHTML = parts.join('');
    breadcrumbEl.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => {
        const crumb = crumbs[Number(btn.dataset.idx || 0)];
        if (!crumb || crumb.level === 'url') {
          setGraphDrilldown({ level: 'url', urlId: null, viewportId: null });
        } else if (crumb.level === 'viewport') {
          setGraphDrilldown({ level: 'viewport', urlId: crumb.urlId, viewportId: null });
        }
      });
    });
  }

  function update(payload) {
    // Badges encode the dominant hidden lower-layer cue type (color + glyph).
    // Own-layer cues are rendered through their primary visual channels instead
    // of being duplicated in a badge.
    function cueBadgeClass(d) {
      if (!d || !(d.badgeCount > 0)) return { circleClass: null, textClass: null, glyph: '', hidden: true };
      const rollupType = dominantRollupCueType(d);
      if (rollupType) {
        return {
          circleClass: `rollup-red cue-${rollupType}`,
          textClass: 'on-stroke',
          glyph: CUE_GLYPH[rollupType] || '',
          hidden: false,
        };
      }
      return { circleClass: null, textClass: null, glyph: '', hidden: true };
    }

    graphMode = payload.mode || 'url';
    emptyEl.textContent = payload.mode === 'url' ? 'no navigation yet.' : 'no child nodes yet.';
    renderBreadcrumb(payload);
    const levelEl = document.getElementById('graph-level');
    const nodeCountEl = document.getElementById('graph-node-count');
    const edgeCountEl = document.getElementById('graph-edge-count');
    if (levelEl)     levelEl.textContent = payload.mode === 'url' ? 'URLs' : (payload.mode === 'viewport' ? 'viewports' : 'actions');
    if (nodeCountEl) nodeCountEl.textContent = String((payload.nodes || []).length);
    if (edgeCountEl) edgeCountEl.textContent = String((payload.links || []).length);

    const previousNodeIds = new Set(nodesData.map(n => n.id));
    const previousLinkKeys = new Set(linksData.map(e => `${edgeEndpointId(e.source)}|${edgeEndpointId(e.target)}`));
    const incomingNodes = payload.nodes || [];
    const incomingLinks = payload.links || [];
    const structureChanged = incomingNodes.length !== nodesData.length ||
      incomingLinks.length !== linksData.length ||
      incomingNodes.some(n => !previousNodeIds.has(n.id)) ||
      incomingLinks.some(e => !previousLinkKeys.has(`${edgeEndpointId(e.source)}|${edgeEndpointId(e.target)}`));

    const prevById = new Map(nodesData.map(n => [n.id, n]));
    nodesData = incomingNodes.map(src => {
      const prev = prevById.get(src.id);
      return Object.assign(prev || {}, normalizeGraphNode(src));
    });
    linksData = incomingLinks.map(e => ({ ...e, mode: payload.mode }));
    if (selectedEdgeKey !== null) {
      const selectedEdge = linksData.find(e => graphEdgeKey(e) === selectedEdgeKey);
      if (selectedEdge) selectedEdgeData = selectedEdge;
      else {
        selectedEdgeKey = null;
        selectedEdgeData = null;
        renderSelection(null);
        highlightTimelineActionStep(null);
      }
    }
    arrangeGraphNodes(nodesData, prevById, linksData, graphMode);
    const maxVisitCount = Math.max(1, trajectoryMaxVisitCount(), ...nodesData.map(graphNodeVisitCount));
    updateGraphLegend(maxVisitCount, nodesData.length > 0);

    emptyEl.style.display = nodesData.length ? 'none' : 'flex';

    linkSel = linkG.selectAll('path.graph-link').data(linksData, d => graphEdgeKey(d));
    linkSel.exit().remove();
    linkSel = linkSel.enter().append('path').attr('class', 'graph-link').merge(linkSel);
    linkSel
      .on('click', (event, d) => { event.stopPropagation(); selectGraphEdge(d); })
      .classed('cycle', d => !!d.isCycleEdge)
      .classed('selected', d => graphEdgeKey(d) === selectedEdgeKey)
      .attr('stroke-width', d => {
        const count = d.count || 1;
        const extra = 1.5 * Math.log2(count);
        return d.isCycleEdge ? Math.min(8, 2 + extra) : Math.min(6, 1 + extra);
      });

    nodeSel = nodeG.selectAll('g.graph-node').data(nodesData, d => d.id);
    nodeSel.exit().remove();
    const enter = nodeSel.enter().append('g')
      .attr('class', 'graph-node')
      .call(drag())
      .on('click', (event, d) => { event.stopPropagation(); selectGraphNode(d); })
      .on('dblclick', (event, d) => { event.stopPropagation(); hideTooltip(); drillGraphNode(d); })
      .on('mouseenter', showTooltip)
      .on('mousemove', moveTooltip)
      .on('mouseleave', hideTooltip);
    enter.append('circle').attr('r', 8);
    // Cue-ring: outer stroke that carries the dominant cue color so the node's
    // Viridis action-count fill stays readable underneath (outline §S2).
    enter.append('circle').attr('class', 'cue-ring').attr('r', 8);
    enter.append('path').attr('class', 'graph-node-shape');
    enter.append('path').attr('class', 'graph-node-cue-shape');
    enter.append('text').attr('class', 'graph-node-label').attr('dx', 12).attr('dy', 4);
    const badgeEnter = enter.append('g').attr('class', 'node-cue-badge');
    badgeEnter.append('circle').attr('r', 8);
    badgeEnter.append('text');
    nodeSel = enter.merge(nodeSel);
    nodeSel
      .classed('root', d => d.isRoot)
      .classed('url', d => d.type === 'url')
      .classed('viewport', d => d.type === 'viewport')
      .classed('action', d => d.type === 'action')
      .classed('drillable', d => !!d.drillable)
      .classed('current', d => !!d.isCurrent)
      .classed('running', d => isRunningGraphNode(d))
      .classed('selected', d => d.id === selectedNodeId)
      .classed('start', d => !!d.isStart)
      .classed('end', d => !!d.isEnd)
      .style('--graph-node-fill', d => graphNodeFill(d, maxVisitCount));
    nodeSel.select('circle:not(.cue-ring)').attr('r', d => graphNodeRadius(d));
    nodeSel.select('circle.cue-ring').each(function(d) {
      const sel = d3.select(this);
      const cueType = ownCueRingType(d);
      const baseR = graphNodeRadius(d);
      sel.attr('r', baseR + 3)
        .attr('class', cueType ? `cue-ring cue-${cueType}` : 'cue-ring')
        .style('display', cueType ? null : 'none');
    });
    nodeSel.select('path.graph-node-cue-shape').each(function(d) {
      const sel = d3.select(this);
      const isEndpoint = !!(d.isStart || d.isEnd);
      const cueType = ownCueRingType(d);
      sel.attr('d', levelEndpointShape(d))
        .attr('class', cueType && isEndpoint ? `graph-node-cue-shape cue-${cueType}` : 'graph-node-cue-shape')
        .style('display', cueType && isEndpoint ? null : 'none');
    });
    nodeSel.select('path.graph-node-shape')
      .attr('d', d => levelEndpointShape(d))
      .style('display', d => (d.isStart || d.isEnd) ? null : 'none');
    nodeSel.select('text.graph-node-label').text(displayGraphNodeLabel);
    const badgeSel = nodeSel.select('g.node-cue-badge');
    badgeSel.each(function(d) {
      const sel = d3.select(this);
      const meta = cueBadgeClass(d);
      if (meta.hidden) {
        sel.style('display', 'none');
        return;
      }
      sel.style('display', null);
      const r = graphNodeRadius(d);
      sel.attr('transform', `translate(${r + 4},${-(r + 4)})`);
      // Glyph alone for badgeCount=1; glyph+count when ≥2 so reviewers see how
      // many child cues rolled up without losing the cue-type signal.
      const label = d.badgeCount >= 2 ? `${meta.glyph}${d.badgeCount}` : meta.glyph;
      sel.select('circle')
        .attr('class', meta.circleClass)
        .attr('r', d.badgeCount >= 10 ? 10 : 8);
      sel.select('text')
        .attr('class', meta.textClass)
        .text(label);
    });

    simulation.nodes(nodesData);
    simulation.force('link').links(linksData);
    if (structureChanged) {
      simulation.alpha(1);
      for (let i = 0; i < 300; i++) simulation.tick();
      simulation.alpha(0);
      ticked();
    } else {
      simulation.alpha(Math.max(simulation.alpha(), 0.06)).restart();
    }
  }


  function reset() {
    nodesData = [];
    linksData = [];
    graphRenderDirty = false;
    linkG.selectAll('*').remove();
    nodeG.selectAll('*').remove();
    hideTooltip();
    updateGraphLegend(1, false);
    breadcrumbEl.innerHTML = '<span>URL layer</span>';
    emptyEl.style.display = 'flex';
    emptyEl.textContent = 'no navigation yet.';
    simulation.nodes([]);
    simulation.force('link').links([]);
  }

  function refreshSelection() {
    nodeG.selectAll('g.graph-node').classed('selected', d => d.id === selectedNodeId);
    linkG.selectAll('path.graph-link').classed('selected', d => graphEdgeKey(d) === selectedEdgeKey);
  }

  function refreshRunning() {
    nodeG.selectAll('g.graph-node').classed('running', d => isRunningGraphNode(d));
  }

  svg.on('click', () => clearGraphSelection());

  return { update, reset, resize, refreshSelection, refreshRunning, fitToNodes };
})();

function isGraphViewActive() {
  return document.body.classList.contains('view-graph');
}

function updateGraph({ force = false } = {}) {
  if (!force && !isGraphViewActive()) {
    graphRenderDirty = true;
    return;
  }
  graphRenderDirty = false;
  graph.update(selectedGraphData());
}

function scheduleGraphUpdate() {
  updateGraph();
}

function resetGraph()  { resetTrajectoryGraphState(); clearGraphSelection(); graphRenderDirty = false; graph.reset(); }
function resizeGraph() { graph.resize(); }

window.updateGraph = updateGraph;
window.resetGraph = resetGraph;
window.resizeGraph = resizeGraph;
window.clearGraphSelection = clearGraphSelection;
window.selectGraphActionForStep = selectGraphActionForStep;
window.recordActionExecution = recordActionExecution;
window.setGraphRunningStep = setGraphRunningStep;
window.clearGraphRunningStep = clearGraphRunningStep;
window.setTrajectoryOutcome = setTrajectoryOutcome;
window.actionNodeForStep = actionNodeForStep;
window.hydrateNoopEvidence = hydrateNoopEvidence;
