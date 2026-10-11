let selectedNodeId = null;
let selectedNodeData = null;
let selectedEdgeKey = null;
let selectedEdgeData = null;

function selectGraphNode(d) {
  if (!d) return;
  if (selectedNodeId === d.id && selectedEdgeKey === null) {
    selectedNodeId = null;
    selectedNodeData = null;
  } else {
    selectedNodeId = d.id;
    selectedNodeData = d;
    selectedEdgeKey = null;
    selectedEdgeData = null;
  }
  renderSelection(selectedNodeData);
  highlightTimelineActionStep(timelineStepForGraphNode(selectedNodeData));
  updateGraphSelectionClass();
}

function graphEdgeKey(edge) {
  if (!edge) return null;
  const source = edgeEndpointId(edge.source);
  const target = edgeEndpointId(edge.target);
  if (!source || !target) return null;
  return `${source}|${target}`;
}

function selectGraphEdge(d) {
  const key = graphEdgeKey(d);
  if (!key) return;
  if (selectedEdgeKey === key) {
    selectedEdgeKey = null;
    selectedEdgeData = null;
    renderSelection(null);
    highlightTimelineActionStep(null);
  } else {
    selectedNodeId = null;
    selectedNodeData = null;
    selectedEdgeKey = graphEdgeKey(d);
    selectedEdgeData = d;
    renderGraphEdgeSelection(selectedEdgeData);
    highlightTimelineActionStep(timelineStepForGraphEdge(selectedEdgeData));
  }
  updateGraphSelectionClass();
}

function selectGraphActionForStep(stepId) {
  const key = stepId != null ? String(stepId) : null;
  if (key == null) {
    clearGraphSelection();
    return false;
  }
  const actionId = actionNodeIdByStep.get(key);
  const actionNode = actionId ? trajectoryActions.get(actionId) : null;
  if (!actionNode) {
    clearGraphSelection();
    return false;
  }
  clearGraphDrillAnchor();
  graphDrilldown = { level: 'action', urlId: actionNode.urlId, viewportId: actionNode.viewportId };
  selectedEdgeKey = null;
  selectedEdgeData = null;
  selectedNodeId = actionNode.id;
  selectedNodeData = actionNode;
  updateGraph();
  return true;
}

function clearGraphSelection() {
  if (selectedNodeId === null && selectedEdgeKey === null) return;
  selectedNodeId = null;
  selectedNodeData = null;
  selectedEdgeKey = null;
  selectedEdgeData = null;
  renderSelection(null);
  highlightTimelineActionStep(null);
  updateGraphSelectionClass();
}

function timelineStepForGraphNode(d) {
  if (!d) return null;
  if (d.step != null) return d.step;
  if (d.lastStep != null) return d.lastStep;
  return d.firstStep != null ? d.firstStep : null;
}

function timelineStepForGraphEdge(edge) {
  const target = graphEdgeEndpointData(edge, 'target');
  const source = graphEdgeEndpointData(edge, 'source');
  return timelineStepForGraphNode(target) ?? timelineStepForGraphNode(source);
}

function updateGraphSelectionClass() {
  if (typeof graph !== 'undefined' && graph && graph.refreshSelection) {
    graph.refreshSelection();
  }
}

function updateGraphRunningClass() {
  if (typeof graph !== 'undefined' && graph && graph.refreshRunning) {
    graph.refreshRunning();
  }
}

function graphEdgeEndpointData(edge, side) {
  const endpoint = edge && edge[side];
  if (!endpoint) return null;
  if (typeof endpoint === 'object' && endpoint.id && endpoint.type) return endpoint;
  const id = edgeEndpointId(endpoint);
  if (!id) return typeof endpoint === 'object' ? endpoint : null;
  const actionNode = trajectoryActions.get(id);
  if (actionNode) return actionNode;
  const viewportNode = trajectoryViewports.get(id);
  if (viewportNode) {
    return {
      ...viewportNode,
      type: 'viewport',
      actionStepCount: actionStepCountForActionIds(viewportNode.actionIds),
      actionCount: viewportNode.actionIds ? viewportNode.actionIds.size : 0,
      actionPreviews: collectActionPreviewArtifacts(viewportNode.actionIds),
    };
  }
  const urlNode = trajectoryNodes.get(id);
  if (urlNode) {
    return {
      ...urlNode,
      label: trajectoryLabelFor(urlNode),
      type: 'url',
      viewportCount: urlNode.viewportIds ? urlNode.viewportIds.size : 0,
      actionStepCount: actionStepCountForActionIds(urlNode.actionIds),
      actionCount: urlNode.actionIds ? urlNode.actionIds.size : 0,
      actionPreviews: collectActionPreviewArtifacts(urlNode.actionIds),
    };
  }
  return typeof endpoint === 'object' ? endpoint : { id, label: id };
}

function graphEdgeEndpointLabel(endpoint) {
  if (!endpoint) return '—';
  if (endpoint.label) return endpoint.label;
  if (endpoint.host) {
    const path = endpoint.path && endpoint.path !== '/' ? endpoint.path : '';
    return `${endpoint.host}${path}`;
  }
  if (endpoint.actionName) return endpoint.actionName;
  return endpoint.id || '—';
}

function graphEdgeLayerLabel(mode) {
  if (mode === 'action') return 'action';
  if (mode === 'viewport') return 'viewport';
  if (mode === 'url') return 'url';
  return 'graph';
}

function graphEdgeEvidenceAnchorNode(edge) {
  const target = graphEdgeEndpointData(edge, 'target');
  const source = graphEdgeEndpointData(edge, 'source');
  if (target && target.type === 'action' && target.artifacts) return target;
  if (source && source.type === 'action' && source.artifacts) return source;
  return target || source;
}

function edgeActionPreviews(edge) {
  const previews = [];
  const seen = new Set();
  const pushPreview = preview => {
    if (!preview || !preview.path) return;
    const key = `${preview.path}|${preview.label || ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    previews.push(preview);
  };
  const pushEndpoint = endpoint => {
    if (!endpoint) return;
    if (endpoint.type === 'action') pushPreview(actionPreviewArtifactsFor(endpoint));
    (endpoint.actionPreviews || []).forEach(pushPreview);
  };
  pushEndpoint(graphEdgeEndpointData(edge, 'source'));
  pushEndpoint(graphEdgeEndpointData(edge, 'target'));
  return previews;
}

function renderEdgeReplayArtifacts(edge) {
  const anchorNode = graphEdgeEvidenceAnchorNode(edge);
  const actionReplay = anchorNode && anchorNode.type === 'action'
    ? renderActionArtifacts(anchorNode.artifacts, anchorNode)
    : '';
  return actionReplay + renderActionPreviewGallery(edgeActionPreviews(edge));
}

function renderGraphEdgeSelection(edge) {
  const titleEl = document.getElementById('side-step-title');
  const replayEl = document.getElementById('side-replay');
  const infoEl = document.getElementById('side-selection');
  const source = graphEdgeEndpointData(edge, 'source');
  const target = graphEdgeEndpointData(edge, 'target');
  const anchorNode = graphEdgeEvidenceAnchorNode(edge);
  const layer = graphEdgeLayerLabel(edge && edge.mode);
  const sourceStep = timelineStepForGraphNode(source);
  const targetStep = timelineStepForGraphNode(target);
  const title = edge && edge.isCycleEdge ? 'Loop edge' : 'Graph edge';
  const rows = [
    `<div class="bullet"><span class="dot">•</span><span><span class="k">level</span> <span class="v">${escHtml(layer)} edge</span></span></div>`,
    `<div class="bullet"><span class="dot">•</span><span><span class="k">from</span> <span class="v">${escHtml(graphEdgeEndpointLabel(source))}</span></span></div>`,
    `<div class="bullet"><span class="dot">•</span><span><span class="k">to</span> <span class="v">${escHtml(graphEdgeEndpointLabel(target))}</span></span></div>`,
    `<div class="bullet"><span class="dot">•</span><span><span class="k">count</span> <span class="v">${edge && edge.count ? edge.count : 1}</span></span></div>`,
  ];
  if (sourceStep != null) rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">source step</span> <span class="v">#${sourceStep}</span></span></div>`);
  if (targetStep != null) rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">target step</span> <span class="v">#${targetStep}</span></span></div>`);
  if (edge && edge.isCycleEdge) rows.push('<div class="bullet"><span class="dot">•</span><span><span class="k">cue</span> <span class="v">loop edge</span></span></div>');

  if (titleEl) {
    titleEl.className = 'side-step-title';
    titleEl.textContent = title;
  }
  if (replayEl) {
    replayEl.innerHTML = renderEdgeReplayArtifacts(edge) || '<div class="side-empty">no replay artifacts for this edge.</div>';
    hydrateNoopEvidence(replayEl);
  }
  if (infoEl) {
    infoEl.innerHTML = rows.join('');
  }
  renderRightPanelAuxiliarySections(anchorNode && anchorNode.llmInference, anchorNode && anchorNode.artifacts);
}

function renderGraphNodeSelection(d) {
  const titleEl = document.getElementById('side-step-title');
  const replayEl = document.getElementById('side-replay');
  const infoEl = document.getElementById('side-selection');
  const rows = [];
  const stepNum = d.step ?? d.firstStep ?? d.lastStep;
  const title = stepNum != null ? `Step #${stepNum}` : (d.label || d.fullUrl || d.id);
  rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">level</span> <span class="v">${escHtml(d.type || '—')}</span></span></div>`);
  if (d.host)        rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">host</span> <span class="v">${escHtml(d.host)}</span></span></div>`);
  if (d.path)        rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">path</span> <span class="v">${escHtml(d.path || '/')}</span></span></div>`);
  if (d.size)        rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">size</span> <span class="v">${escHtml(d.size)}</span></span></div>`);
  if (d.scroll)      rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">scroll</span> <span class="v">${escHtml(d.scroll)}</span></span></div>`);
  if (d.actionName)  rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">action</span> <span class="v">${escHtml(d.actionName)}</span></span></div>`);
  if (d.argsText)    rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">args</span> <span class="v">${escHtml(d.argsText)}</span></span></div>`);
  if (d.actionStepCount != null) rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">total steps</span> <span class="v">${d.actionStepCount}</span></span></div>`);
  if (d.visits != null)        rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">visits</span> <span class="v">${d.visits}</span></span></div>`);
  if (d.viewportCount != null) rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">viewports</span> <span class="v">${d.viewportCount}</span></span></div>`);
  if (d.actionCount != null)   rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">unique actions</span> <span class="v">${d.actionCount}</span></span></div>`);
  rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">first step</span> <span class="v">#${d.firstStep ?? d.step ?? '—'}</span></span></div>`);
  rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">last step</span> <span class="v">#${d.lastStep ?? d.step ?? '—'}</span></span></div>`);
  if (d.drillable)   rows.push(`<div class="bullet"><span class="dot">•</span><span><span class="k">tip</span> <span class="v">double-click to drill in</span></span></div>`);

  if (titleEl) {
    titleEl.className = 'side-step-title';
    titleEl.textContent = title;
  }
  const replayBody = renderActionArtifacts(d.artifacts, d) + renderActionPreviewGallery(d.actionPreviews);
  if (replayEl) {
    replayEl.innerHTML = replayBody || '<div class="side-empty">no replay artifacts.</div>';
    hydrateNoopEvidence(replayEl);
  }
  if (infoEl) {
    infoEl.innerHTML = rows.length ? rows.join('') : '<div class="side-empty">no info.</div>';
  }
  renderRightPanelAuxiliarySections(d.llmInference, d.artifacts);
}

function renderSelection(d) {
  const titleEl = document.getElementById('side-step-title');
  const replayEl = document.getElementById('side-replay');
  const infoEl = document.getElementById('side-selection');
  if (!d) {
    if (titleEl) {
      titleEl.className = 'side-step-title side-empty';
      titleEl.textContent = 'no action step selected.';
    }
    if (replayEl) replayEl.innerHTML = '<div class="side-empty">no action step selected.</div>';
    if (infoEl) infoEl.innerHTML = '<div class="side-empty">no action step selected.</div>';
    renderRightPanelAuxiliarySections(null, null);
    return;
  }
  if (d.type === 'action') {
    if (typeof renderActionGroupAdditionalInfo === 'function') {
      renderActionGroupAdditionalInfo(d);
      return;
    }
  }
  renderGraphNodeSelection(d);
}

function scheduleGraphFit(delay = 30) {
  if (typeof graph === 'undefined' || !graph || !graph.fitToNodes) return;
  setTimeout(() => {
    if (!isGraphViewActive()) return;
    graph.fitToNodes();
  }, delay);
}

function setGraphDrilldown(next) {
  clearGraphDrillAnchor();
  graphDrilldown = next;
  updateGraph();
  scheduleGraphFit();
}
