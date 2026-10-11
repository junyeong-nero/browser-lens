// ── graph layout helpers ─────────────────────────────────
const GRAPH_TREE_LAYER_SPACING = 96;
const GRAPH_TREE_SIBLING_SPACING = 118;

function graphRootPosition(graphMode, index = 0, count = 1) {
  return {
    x: graphMode === 'url' ? (index - (count - 1) / 2) * 140 : 0,
    y: graphMode === 'url' ? -180 : -220,
  };
}

function graphTargetX(d) {
  if (d && d.isRoot && d._rootPin) return d._rootPin.x;
  if (d && Number.isFinite(d._targetX)) return d._targetX;
  return 0;
}

function graphTargetY(d) {
  if (d && d.isRoot && d._rootPin) return d._rootPin.y;
  if (d && Number.isFinite(d._targetY)) return d._targetY;
  return 90;
}

function normalizeGraphNode(src) {
  return {
    isRoot: false,
    isCurrent: false,
    drillable: false,
    ...src,
  };
}

function graphDrillAnchorForNode(node, graphMode) {
  if (graphMode === 'url' || !graphDrillAnchor || !node) return null;
  if (graphDrillAnchor.id !== node.id) return null;
  if (graphDrillAnchor.toLevel !== graphMode) return null;
  if (!Number.isFinite(graphDrillAnchor.x) || !Number.isFinite(graphDrillAnchor.y)) return null;
  return { x: graphDrillAnchor.x, y: graphDrillAnchor.y };
}

function graphLinkEndpointId(endpoint) {
  if (endpoint && typeof endpoint === 'object') return endpoint.id;
  return endpoint;
}

function isLinearAcyclicGraph(nodes, acyclicLinks, linksData) {
  if (linksData.some(e => e.isCycleEdge)) return false;
  if (nodes.length <= 1) return true;
  if (acyclicLinks.length !== nodes.length - 1) return false;
  const ids = new Set(nodes.map(n => n.id));
  const incoming = new Map(nodes.map(n => [n.id, 0]));
  const outgoing = new Map(nodes.map(n => [n.id, 0]));
  acyclicLinks.forEach(link => {
    const sourceId = graphLinkEndpointId(link.source);
    const targetId = graphLinkEndpointId(link.target);
    if (!ids.has(sourceId) || !ids.has(targetId)) return;
    outgoing.set(sourceId, (outgoing.get(sourceId) || 0) + 1);
    incoming.set(targetId, (incoming.get(targetId) || 0) + 1);
  });
  let startCount = 0;
  let endCount = 0;
  for (const node of nodes) {
    const inCount = incoming.get(node.id) || 0;
    const outCount = outgoing.get(node.id) || 0;
    if (inCount > 1 || outCount > 1) return false;
    if (inCount === 0) startCount += 1;
    if (outCount === 0) endCount += 1;
  }
  return startCount === 1 && endCount === 1;
}

function buildTopDownLayoutTargets(nodes, linksData, graphMode) {
  const orderedNodes = [...nodes].sort((a, b) => {
    const bySequence = (a._sequenceIndex || 0) - (b._sequenceIndex || 0);
    if (bySequence) return bySequence;
    return String(a.id).localeCompare(String(b.id));
  });
  const topY = graphMode === 'url' ? -180 : -220;
  const acyclicLinks = linksData.filter(e => !e.isCycleEdge);
  if (isLinearAcyclicGraph(orderedNodes, acyclicLinks, linksData)) {
    return new Map(orderedNodes.map((node, index) => [node.id, { x: 0, y: topY + index * GRAPH_TREE_LAYER_SPACING }]));
  }

  const nodesById = new Map(orderedNodes.map(node => [node.id, node]));
  const childrenById = new Map(orderedNodes.map(node => [node.id, []]));
  const incomingCount = new Map(orderedNodes.map(node => [node.id, 0]));
  acyclicLinks.forEach(link => {
    const sourceId = graphLinkEndpointId(link.source);
    const targetId = graphLinkEndpointId(link.target);
    if (!nodesById.has(sourceId) || !nodesById.has(targetId) || sourceId === targetId) return;
    childrenById.get(sourceId).push(targetId);
    incomingCount.set(targetId, (incomingCount.get(targetId) || 0) + 1);
  });
  childrenById.forEach(children => {
    children.sort((a, b) => {
      const left = nodesById.get(a);
      const right = nodesById.get(b);
      return (left._sequenceIndex || 0) - (right._sequenceIndex || 0);
    });
  });

  const roots = orderedNodes.filter(node => (incomingCount.get(node.id) || 0) === 0);
  const queue = (roots.length ? roots : orderedNodes.slice(0, 1)).map(node => ({ id: node.id, depth: 0 }));
  const depthById = new Map();
  while (queue.length) {
    const current = queue.shift();
    if (depthById.has(current.id) && depthById.get(current.id) <= current.depth) continue;
    depthById.set(current.id, current.depth);
    for (const childId of childrenById.get(current.id) || []) {
      queue.push({ id: childId, depth: current.depth + 1 });
    }
  }
  orderedNodes.forEach((node, index) => {
    if (!depthById.has(node.id)) depthById.set(node.id, index);
  });

  const levels = new Map();
  orderedNodes.forEach(node => {
    const depth = depthById.get(node.id) || 0;
    if (!levels.has(depth)) levels.set(depth, []);
    levels.get(depth).push(node);
  });

  const targets = new Map();
  Array.from(levels.keys()).sort((a, b) => a - b).forEach(depth => {
    const levelNodes = levels.get(depth).sort((a, b) => {
      const bySequence = (a._sequenceIndex || 0) - (b._sequenceIndex || 0);
      if (bySequence) return bySequence;
      return String(a.id).localeCompare(String(b.id));
    });
    levelNodes.forEach((node, index) => {
      targets.set(node.id, {
        x: (index - (levelNodes.length - 1) / 2) * GRAPH_TREE_SIBLING_SPACING,
        y: topY + depth * GRAPH_TREE_LAYER_SPACING,
      });
    });
  });
  return targets;
}

function arrangeGraphNodes(nodes, previousById, linksData, graphMode) {
  const rootNodes = nodes.filter(n => n.isRoot);
  const layoutTargets = buildTopDownLayoutTargets(nodes, linksData, graphMode);
  const pinRoots = graphMode !== 'url';
  rootNodes.forEach((node, index) => {
    const pinned = graphDrillAnchorForNode(node, graphMode) || graphRootPosition(graphMode, index, rootNodes.length);
    const target = layoutTargets.get(node.id) || pinned;
    node._targetX = target.x;
    node._targetY = target.y;
    if (pinRoots) {
      node._rootPin = pinned;
      node.fx = pinned.x;
      node.fy = pinned.y;
    } else {
      node._rootPin = null;
      node.fx = null;
      node.fy = null;
    }
    if (!previousById.has(node.id) || !Number.isFinite(node.x) || !Number.isFinite(node.y)) {
      node.x = target.x;
      node.y = target.y;
    }
  });
  nodes.filter(n => !n.isRoot).forEach((node) => {
    node.fx = null;
    node.fy = null;
    const target = layoutTargets.get(node.id) || { x: 0, y: 90 };
    node._targetX = target.x;
    node._targetY = target.y;
    if (previousById.has(node.id) && Number.isFinite(node.x) && Number.isFinite(node.y)) return;
    node.x = target.x;
    node.y = target.y;
  });
}

function graphLinkPath(d, radiusForNode) {
  const source = d.source || {};
  const target = d.target || {};
  const sx = source.x || 0;
  const sy = source.y || 0;
  const tx = target.x || 0;
  const ty = target.y || 0;
  if ((source.id || source) === (target.id || target)) {
    const r = 22 + Math.min(14, Math.log2((d.count || 1) + 1) * 4);
    return `M ${sx} ${sy - 8} C ${sx + r} ${sy - r * 1.6}, ${sx + r * 1.8} ${sy + r * 1.2}, ${sx + 4} ${sy + 8}`;
  }
  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  const sourceR = (typeof source === 'object' && source) ? radiusForNode(source) : 7;
  const targetR = (typeof target === 'object' && target) ? radiusForNode(target) : 7;
  const x1 = sx + ux * sourceR;
  const y1 = sy + uy * sourceR;
  const x2 = tx - ux * targetR;
  const y2 = ty - uy * targetR;
  return `M ${x1} ${y1} L ${x2} ${y2}`;
}
