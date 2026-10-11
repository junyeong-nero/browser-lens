function formatArgs(obj) {
  return Object.entries(obj)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ');
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function safeMarkdownHref(url) {
  const trimmed = String(url || '').trim();
  if (/^(https?:|mailto:)/i.test(trimmed)) return trimmed;
  if (/^\/(?!\/)/.test(trimmed) || /^#/.test(trimmed)) return trimmed;
  return '';
}

function restoreMarkdownPlaceholders(html, placeholders) {
  return html.replace(/\u0000(\d+)\u0000/g, (_match, index) => placeholders[Number(index)] || '');
}

function renderInlineMarkdown(rawText) {
  const placeholders = [];
  const stash = html => {
    const token = `\u0000${placeholders.length}\u0000`;
    placeholders.push(html);
    return token;
  };
  let text = String(rawText || '').replace(/`([^`\n]+)`/g, (_match, code) => (
    stash(`<code>${escHtml(code)}</code>`)
  ));
  text = text.replace(/!?\[([^\]\n]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
    if (match.startsWith('!')) return label;
    const safeHref = safeMarkdownHref(href);
    if (!safeHref) return label;
    return stash(
      `<a href="${escHtml(safeHref)}" target="_blank" rel="noreferrer">${escHtml(label)}</a>`
    );
  });
  let html = escHtml(text);
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  html = html.replace(/(^|[^\*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  html = html.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');
  return restoreMarkdownPlaceholders(html, placeholders);
}

function renderMarkdownSafe(markdown) {
  const lines = String(markdown || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let paragraph = [];
  let listItems = [];
  let listType = null;
  let inFence = false;
  let fenceLanguage = '';
  let fenceLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join(' '))}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!listItems.length) return;
    const tag = listType === 'ol' ? 'ol' : 'ul';
    blocks.push(`<${tag}>${listItems.map(item => `<li>${renderInlineMarkdown(item)}</li>`).join('')}</${tag}>`);
    listItems = [];
    listType = null;
  };
  const flushFence = () => {
    const language = fenceLanguage.replace(/[^\w-]/g, '');
    const languageClass = language ? ` class="language-${escHtml(language)}"` : '';
    blocks.push(`<pre><code${languageClass}>${escHtml(fenceLines.join('\n'))}</code></pre>`);
    fenceLines = [];
    fenceLanguage = '';
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^```\s*([\w-]*)\s*$/);
    if (fenceMatch) {
      if (inFence) {
        flushFence();
        inFence = false;
      } else {
        flushParagraph();
        flushList();
        inFence = true;
        fenceLanguage = fenceMatch[1] || '';
      }
      continue;
    }
    if (inFence) {
      fenceLines.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const headingMatch = line.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = Math.min(4, headingMatch[1].length + 2);
      blocks.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }
    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    const orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    if (unorderedMatch || orderedMatch) {
      flushParagraph();
      const nextType = orderedMatch ? 'ol' : 'ul';
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      listItems.push((orderedMatch || unorderedMatch)[1]);
      continue;
    }
    flushList();
    paragraph.push(line.trim());
  }
  if (inFence) flushFence();
  flushParagraph();
  flushList();

  return `<div class="message-markdown">${blocks.join('')}</div>`;
}
