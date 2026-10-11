// Set-based ARIA diff per outline §S3 — no LCS, no library. Lines unique to
// the pre-state are removals; lines unique to the post-state are additions;
// shared lines are context. Capped output keeps the panel snappy.
function ariaDiffLines(preText, postText, maxLines = 200) {
  const splitLines = (text) => String(text || '').split('\n').map(line => line.trim()).filter(Boolean);
  const preLines = splitLines(preText);
  const postLines = splitLines(postText);
  const preSet = new Set(preLines);
  const postSet = new Set(postLines);
  const out = [];
  let truncated = false;
  for (const line of preLines) {
    if (!postSet.has(line)) {
      if (out.length >= maxLines) { truncated = true; break; }
      out.push({ kind: 'removed', text: line });
    }
  }
  if (!truncated) {
    for (const line of postLines) {
      if (!preSet.has(line)) {
        if (out.length >= maxLines) { truncated = true; break; }
        out.push({ kind: 'added', text: line });
      }
    }
  }
  return { lines: out, truncated, preCount: preLines.length, postCount: postLines.length };
}

function renderAriaPrePostDiff(preText, postText) {
  if (!preText && !postText) return '';
  const diff = ariaDiffLines(preText, postText);
  if (!diff.lines.length) {
    return `
      <div class="llm-raw-title">ARIA diff</div>
      <div class="aria-diff aria-diff-empty">No structural change between pre and post ARIA snapshots (${diff.preCount} → ${diff.postCount} lines).</div>`;
  }
  const rows = diff.lines.map(line => {
    const prefix = line.kind === 'added' ? '+' : '−';
    return `<div class="aria-diff-line ${line.kind}"><span class="aria-diff-prefix">${prefix}</span><span class="aria-diff-text">${escHtml(line.text)}</span></div>`;
  });
  const note = diff.truncated ? '<div class="aria-diff-truncated">…diff truncated.</div>' : '';
  return `
    <div class="llm-raw-title">ARIA diff (pre → post)</div>
    <div class="aria-diff">${rows.join('')}${note}</div>`;
}

function renderActionArtifacts(artifacts, actionContext = null) {
  if (!artifacts) return '';
  const actionVideo = replayArtifactHref(artifacts.action_video_path, 'history');
  const actionClip = replayArtifactHref(artifacts.action_clip_gif_path, 'history');
  const fallbackActionGif = replayArtifactHref(artifacts.action_gif_path, 'history');
  const beforeShot = replayArtifactHref(artifacts.before_screenshot_path, 'history');
  const afterShot = replayArtifactHref(artifacts.after_screenshot_path || artifacts.screenshot_path, 'history');
  const video = replayArtifactHref(artifacts.video_path, 'video');
  // Outline §F2.4 no-op outcome cue: when the agent's action produced no
  // meaningful state change, surface a banner only after asynchronous evidence
  // checks prove DOM diff, ARIA diff, and screenshot pixel diff are all <= K.
  // The hidden placeholder is removed unless all evidence gates pass.
  const noopPayload = escHtml(JSON.stringify({
    before_metadata_path: artifacts.before_metadata_path,
    after_metadata_path: artifacts.after_metadata_path || artifacts.metadata_path,
    metadata_path: artifacts.metadata_path,
    before_html_path: artifacts.before_html_path,
    html_path: artifacts.html_path || artifacts.after_html_path,
    before_a11y_path: artifacts.before_a11y_path,
    a11y_path: artifacts.a11y_path || artifacts.after_a11y_path,
    before_screenshot_path: artifacts.before_screenshot_path,
    after_screenshot_path: artifacts.after_screenshot_path || artifacts.screenshot_path,
    screenshot_path: artifacts.screenshot_path,
  }));
  const noopAlert = (isNoopDetectionEligibleAction(actionContext) && beforeShot && afterShot)
    ? `<div class="artifact-noop-alert" role="status" hidden data-noop-evidence="true" data-artifacts="${noopPayload}">
         <span class="noop-alert-icon" aria-hidden="true"></span>
         <span class="artifact-noop-text">Checking no-op evidence…</span>
       </div>`
    : '';
  const cards = [
    renderActionReplayVideoCard('Action replay', actionVideo),
    !actionVideo ? renderActionReplayCard('Action replay', actionClip) : '',
    !actionVideo && !actionClip && fallbackActionGif ? renderArtifactCard('Before/after GIF', fallbackActionGif, 'gif') : '',
    noopAlert,
    renderBeforeAfterCompare(beforeShot, afterShot),
  ].filter(Boolean);
  const videoCard = renderArtifactCard('session video', video, 'video');
  const names = [];
  if (artifacts.action_video_path) names.push(`action_video=${escHtml(artifacts.action_video_path)}`);
  if (artifacts.action_clip_gif_path) names.push(`clip=${escHtml(artifacts.action_clip_gif_path)}`);
  if (artifacts.action_gif_path) names.push(`before_after_gif=${escHtml(artifacts.action_gif_path)}`);
  if (artifacts.before_screenshot_path) names.push(`before=${escHtml(artifacts.before_screenshot_path)}`);
  if (artifacts.after_screenshot_path || artifacts.screenshot_path) names.push(`after=${escHtml(artifacts.after_screenshot_path || artifacts.screenshot_path)}`);
  if (artifacts.video_path) names.push(`video=${escHtml(artifacts.video_path)}`);
  const pathDetails = names.length
    ? `<details class="artifact-paths"><summary>Technical paths</summary>${names.map(name => `<div class="bullet"><span class="dot">•</span><span><span class="v">${name}</span></span></div>`).join('')}</details>`
    : '';
  return (cards.length ? `<div class="artifact-compare">${cards.join('')}</div>` : '') + videoCard + pathDetails;
}

function actionPreviewArtifactsFor(action) {
  const artifacts = action && action.artifacts;
  if (!artifacts) return null;
  const previewPath = artifacts.action_video_path || artifacts.action_clip_gif_path || artifacts.action_gif_path || artifacts.after_screenshot_path || artifacts.screenshot_path;
  if (!previewPath) return null;
  return {
    label: action.label || `#${action.step || ''} action`,
    path: previewPath,
    kind: artifacts.action_video_path ? 'video' : ((artifacts.action_clip_gif_path || artifacts.action_gif_path) ? 'gif' : 'image'),
  };
}

function collectActionPreviewArtifacts(actionIds) {
  return Array.from(actionIds || [])
    .map(id => trajectoryActions.get(id))
    .filter(Boolean)
    .sort((a, b) => (a.step - b.step) || (a.order - b.order))
    .map(actionPreviewArtifactsFor)
    .filter(Boolean);
}

function renderActionPreviewGallery(previews) {
  if (!Array.isArray(previews) || !previews.length) return '';
  const cards = previews.map((preview, index) => {
    const href = replayArtifactHref(preview.path, 'history');
    const label = preview.label || `action ${index + 1}`;
    return renderArtifactCard(label, href, preview.kind);
  }).filter(Boolean);
  if (!cards.length) return '';
  return `<div class="bullet"><span class="dot">•</span><span><span class="k">child previews</span> <span class="v">${cards.length} action(s)</span></span></div>` +
    `<div class="artifact-gallery">${cards.join('')}</div>`;
}

function llmInferenceForStep(stepId) {
  if (stepId == null || typeof window.getLlmInferenceForStep !== 'function') return null;
  return window.getLlmInferenceForStep(stepId);
}

function formatRawJson(value) {
  if (value == null) return 'null';
  try {
    return JSON.stringify(value, null, 2);
  } catch (_) {
    return String(value);
  }
}

function renderCodeBox(title, text, options = {}) {
  const kind = options.kind || 'text';
  const href = options.href || '';
  const traceHref = options.traceHref || '';
  const traceField = options.traceField || '';
  const safeHref = href ? escHtml(href) : '';
  const safeTraceHref = traceHref ? escHtml(traceHref) : '';
  const openLink = href
    ? ` <a class="artifact-link" target="_blank" rel="noreferrer" href="${safeHref}">open</a>`
    : '';
  const preAttrs = [
    href ? `data-browser-state-src="${safeHref}" data-browser-state-kind="${escHtml(kind)}"` : '',
    traceHref ? `data-llm-trace-src="${safeTraceHref}" data-llm-trace-field="${escHtml(traceField)}"` : '',
  ].filter(Boolean).join(' ');
  const preAttrText = preAttrs ? ` ${preAttrs}` : '';
  return `
    <div class="codebox" data-codebox>
      <div class="codebox-toolbar">
        <span class="codebox-title">${escHtml(title)}${openLink}</span>
        <button class="codebox-copy" type="button" data-copy-codebox aria-label="Copy ${escHtml(title)}" title="Copy">
          <svg class="btn-icon" aria-hidden="true" viewBox="0 0 24 24" focusable="false">
            <path d="M16 1H4a2 2 0 0 0-2 2v12h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"></path>
          </svg>
          <span>Copy</span>
        </button>
      </div>
      <pre class="codebox-pre${href ? ' browser-state-preview' : ''}"${preAttrText}>${escHtml(text)}</pre>
    </div>`;
}

function llmTraceHref(inference) {
  if (!inference || !inference.tracePath) return '';
  return replayArtifactHref(inference.tracePath, 'history');
}

function renderLlmTraceLink(inference) {
  const traceHref = llmTraceHref(inference);
  return traceHref
    ? `<div class="bullet"><span class="dot">•</span><span><span class="k">LLM trace artifact</span> <a class="artifact-link" target="_blank" rel="noreferrer" href="${escHtml(traceHref)}">open JSON</a></span></div>`
    : '';
}

function renderLlmContextBody(inference) {
  if (!inference) return '';
  const traceHref = llmTraceHref(inference);
  const traceLink = renderLlmTraceLink(inference);
  const body = inference.rawContextOmitted && traceHref
    ? 'Loading raw context from LLM trace...'
    : (inference.rawContextOmitted
        ? 'Raw context omitted from live event. Open the LLM trace artifact for full JSON.'
        : formatRawJson(inference.rawContext));
  const options = inference.rawContextOmitted && traceHref
    ? { kind: 'JSON', traceHref, traceField: 'raw_context' }
    : { kind: 'JSON' };
  return `
    ${traceLink}
    ${renderCodeBox('LLM raw context', body, options)}`;
}

function renderLlmResponseBody(inference) {
  if (!inference) return '';
  const traceHref = llmTraceHref(inference);
  const traceLink = renderLlmTraceLink(inference);
  const body = inference.rawResponseOmitted && traceHref
    ? 'Loading raw response from LLM trace...'
    : (inference.rawResponseOmitted
        ? 'Raw response omitted from live event. Open the LLM trace artifact for full JSON.'
        : formatRawJson(inference.rawResponse));
  const options = inference.rawResponseOmitted && traceHref
    ? { kind: 'JSON', traceHref, traceField: 'raw_response' }
    : { kind: 'JSON' };
  return `
    ${traceLink}
    ${renderCodeBox('LLM response', body, options)}`;
}

function browserStateArtifactInfo(artifacts) {
  if (!artifacts) return null;
  const domHref = replayArtifactHref(artifacts.html_path || artifacts.after_html_path, 'history');
  const ariaHref = replayArtifactHref(artifacts.a11y_path || artifacts.after_a11y_path, 'history');
  const metadataHref = replayArtifactHref(artifacts.metadata_path || artifacts.after_metadata_path, 'history');
  if (!domHref && !ariaHref) return null;
  return {
    domHref,
    ariaHref,
    metadataHref,
    a11ySource: artifacts.a11y_source || '',
    a11yStatus: artifacts.a11y_capture_status || '',
    a11yError: artifacts.a11y_capture_error || '',
  };
}

function renderBrowserStatePreview(title, href, kind) {
  if (!href) return '';
  return renderCodeBox(title, `Open this section to load ${kind} state...`, {
    href,
    kind,
  });
}

function renderBrowserStateMetaRow(label, value) {
  return `<div class="bullet"><span class="dot">•</span><span><span class="k">${escHtml(label)}</span> <span class="v">${escHtml(value)}</span></span></div>`;
}

function renderBrowserStateMetaLink(label, href, linkText) {
  return `<div class="bullet"><span class="dot">•</span><span><span class="k">${escHtml(label)}</span> <a class="artifact-link" target="_blank" rel="noreferrer" href="${escHtml(href)}">${escHtml(linkText)}</a></span></div>`;
}

function renderDomStateBody(artifacts, actionNode) {
  const state = browserStateArtifactInfo(artifacts);
  if (!state || !state.domHref) return '';
  const metaRows = [];
  if (state.metadataHref) metaRows.push(renderBrowserStateMetaLink('State metadata', state.metadataHref, 'open JSON'));
  return `
    ${metaRows.join('')}
    ${renderBrowserStatePreview('DOM snapshot', state.domHref, 'DOM')}`;
}

function renderAriaStateBody(artifacts, actionNode) {
  const state = browserStateArtifactInfo(artifacts);
  if (!state) return '';
  const metaRows = [];
  if (state.a11ySource) metaRows.push(renderBrowserStateMetaRow('ARIA source', state.a11ySource));
  if (state.a11yStatus) metaRows.push(renderBrowserStateMetaRow('ARIA capture', state.a11yStatus));
  if (state.a11yError) metaRows.push(renderBrowserStateMetaRow('ARIA error', state.a11yError));
  if (state.metadataHref) metaRows.push(renderBrowserStateMetaLink('State metadata', state.metadataHref, 'open JSON'));
  const preview = renderBrowserStatePreview('ARIA snapshot', state.ariaHref, 'ARIA');
  if (!metaRows.length && !preview) return '';
  return `
    ${metaRows.join('')}
    ${preview}`;
}

function setOptionalSideSection(section, body, content) {
  if (!section || !body) return;
  if (!content) {
    body.innerHTML = '';
    section.hidden = true;
    section.open = false;
    return;
  }
  body.innerHTML = content;
  section.hidden = false;
}

function renderRightPanelAuxiliarySections(inference, artifacts, actionNode) {
  const llmContextSection = document.getElementById('side-llm-context-section');
  const llmContextBody = document.getElementById('side-llm-context');
  const llmResponseSection = document.getElementById('side-llm-response-section');
  const llmResponseBody = document.getElementById('side-llm-response');
  const domStateSection = document.getElementById('side-dom-state-section');
  const domStateBody = document.getElementById('side-dom-state');
  const ariaStateSection = document.getElementById('side-aria-state-section');
  const ariaStateBody = document.getElementById('side-aria-state');

  const llmContextContent = renderLlmContextBody(inference);
  const llmResponseContent = renderLlmResponseBody(inference);
  const domStateContent = renderDomStateBody(artifacts, actionNode);
  const ariaStateContent = renderAriaStateBody(artifacts, actionNode);
  setOptionalSideSection(llmContextSection, llmContextBody, llmContextContent);
  setOptionalSideSection(llmResponseSection, llmResponseBody, llmResponseContent);
  setOptionalSideSection(domStateSection, domStateBody, domStateContent);
  setOptionalSideSection(ariaStateSection, ariaStateBody, ariaStateContent);
  [
    [llmContextSection, llmContextContent],
    [llmResponseSection, llmResponseContent],
    [domStateSection, domStateContent],
    [ariaStateSection, ariaStateContent],
  ].forEach(([section, content]) => {
    if (!content || !section) return;
    hydrateCodeBoxCopyButtons(section);
    hydrateLlmTraceLoaders(section);
    hydrateBrowserStateButtons(section);
    if (section.open) loadLlmTracePreviews(section);
    if (section.open) loadBrowserStatePreviews(section);
  });
}

// Look up action node by step id for callers that only have stepIds (per-step
// selection path). Returns null when no graph action has been recorded yet
// (e.g. the timeline event arrives before the graph builds).
function actionNodeForStep(stepId) {
  if (stepId == null) return null;
  const actionId = actionNodeIdByStep.get(String(stepId));
  return actionId ? trajectoryActions.get(actionId) : null;
}

async function loadBrowserStatePreviews(container) {
  const previews = Array.from(container.querySelectorAll('pre[data-browser-state-src]'))
    .filter(pre => pre.dataset.browserStateLoaded !== 'true');
  await Promise.all(previews.map(async (pre) => {
    const src = pre.dataset.browserStateSrc;
    const kind = pre.dataset.browserStateKind || 'browser';
    if (!src) return;
    pre.dataset.browserStateLoaded = 'true';
    pre.textContent = `Loading ${kind} state…`;
    try {
      const response = await fetch(src, { cache: 'no-store' });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`.trim());
      const text = await response.text();
      pre.textContent = text || '(empty)';
    } catch (error) {
      pre.dataset.browserStateLoaded = 'false';
      pre.textContent = `Unable to load ${kind} state: ${error?.message ?? String(error)}`;
    }
  }));
}

async function loadLlmTracePreviews(container) {
  const previews = Array.from(container.querySelectorAll('pre[data-llm-trace-src]'))
    .filter(pre => pre.dataset.llmTraceLoaded !== 'true');
  await Promise.all(previews.map(async (pre) => {
    const src = pre.dataset.llmTraceSrc;
    const field = pre.dataset.llmTraceField;
    if (!src || !field) return;
    pre.dataset.llmTraceLoaded = 'true';
    pre.textContent = `Loading ${field} from LLM trace...`;
    try {
      const response = await fetch(src, { cache: 'no-store' });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`.trim());
      const payload = await response.json();
      pre.textContent = formatRawJson(payload ? payload[field] : null);
    } catch (error) {
      pre.dataset.llmTraceLoaded = 'false';
      pre.textContent = `Unable to load ${field} from LLM trace: ${error?.message ?? String(error)}`;
    }
  }));
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', '');
  textArea.style.position = 'fixed';
  textArea.style.left = '-9999px';
  textArea.style.top = '0';
  document.body.appendChild(textArea);
  textArea.select();
  try {
    document.execCommand('copy');
  } finally {
    textArea.remove();
  }
}

function hydrateCodeBoxCopyButtons(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return;
  root.querySelectorAll('[data-copy-codebox]').forEach(button => {
    if (button.dataset.copyBound === 'true') return;
    button.dataset.copyBound = 'true';
    button.addEventListener('click', async () => {
      const box = button.closest('[data-codebox]');
      const pre = box ? box.querySelector('pre') : null;
      const text = pre ? pre.textContent : '';
      try {
        await copyTextToClipboard(text);
        button.classList.add('copied');
        const label = button.querySelector('span');
        if (label) label.textContent = 'Copied';
        window.setTimeout(() => {
          button.classList.remove('copied');
          if (label) label.textContent = 'Copy';
        }, 1200);
      } catch (error) {
        button.classList.add('copy-failed');
        const label = button.querySelector('span');
        if (label) label.textContent = 'Failed';
        window.setTimeout(() => {
          button.classList.remove('copy-failed');
          if (label) label.textContent = 'Copy';
        }, 1600);
      }
    });
  });
}

function hydrateLlmTraceLoaders(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return;
  const detailsNodes = [];
  if (typeof root.matches === 'function' && root.matches('details')) {
    detailsNodes.push(root);
  }
  detailsNodes.push(...root.querySelectorAll('details'));
  detailsNodes.forEach(details => {
    if (!details.querySelector('pre[data-llm-trace-src]')) return;
    if (details.dataset.llmTraceBound === 'true') return;
    details.dataset.llmTraceBound = 'true';
    details.addEventListener('toggle', () => {
      if (details.open) loadLlmTracePreviews(details);
    });
  });
}

function hydrateBrowserStateButtons(root = document) {
  if (!root || typeof root.querySelectorAll !== 'function') return;
  const detailsNodes = [];
  if (typeof root.matches === 'function' && root.matches('details.browser-state-details')) {
    detailsNodes.push(root);
  }
  detailsNodes.push(...root.querySelectorAll('details.browser-state-details'));
  detailsNodes.forEach(details => {
    if (details.dataset.browserStateBound === 'true') return;
    details.dataset.browserStateBound = 'true';
    details.addEventListener('toggle', () => {
      if (details.open) loadBrowserStatePreviews(details);
    });
  });
}
