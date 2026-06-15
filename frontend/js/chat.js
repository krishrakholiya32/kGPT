/* ===== kGPT Chat Logic ===== */

const API = '';
const token = () => localStorage.getItem('kgpt_token');

let isLoading = false;
let currentUser = null;
let lastUserMessage = null;
let abortController = null;
let aborted = false;
let pendingImages = [];
const MAX_IMAGES = 5;
let currentConversationId = null;

// ===== Init =====
async function init() {
  if (!token()) return window.location.href = '/login.html';

  try {
    const res = await fetch(`${API}/api/auth/me`, { headers: authHeaders() });
    if (!res.ok) return logout();
    currentUser = await res.json();
    document.getElementById('user-name').textContent = currentUser.username;
    document.getElementById('user-avatar').textContent = currentUser.username[0].toUpperCase();
  } catch {
    logout();
  }

  initTheme();
  loadConversations();
}

function authHeaders() {
  return { 'Authorization': `Bearer ${token()}`, 'Content-Type': 'application/json' };
}

// ===== Theme Toggle Logic =====
function initTheme() {
  const savedTheme = localStorage.getItem('kgpt_theme') || 'dark';
  if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
  } else {
    document.body.classList.remove('light-theme');
  }
  updateThemeToggleUI(savedTheme);
}

function toggleTheme() {
  const isLight = document.body.classList.toggle('light-theme');
  const currentTheme = isLight ? 'light' : 'dark';
  localStorage.setItem('kgpt_theme', currentTheme);
  updateThemeToggleUI(currentTheme);
}

function updateThemeToggleUI(theme) {
  const toggleBtn = document.getElementById('theme-toggle');
  if (!toggleBtn) return;
  const icon = toggleBtn.querySelector('.theme-icon');
  if (theme === 'light') {
    if (icon) icon.textContent = '\u2600\uFE0F';
  } else {
    if (icon) icon.textContent = '\uD83C\uDF19';
  }
}

function useHint(text) {
  document.getElementById('chat-input').value = text;
  document.getElementById('chat-input').focus();
}

// ===== Send Message =====
async function sendMessage() {
  if (isLoading) { stopGenerating(); return; }
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  const images = pendingImages.slice();
  if (!message && images.length === 0) return;

  input.value = '';
  input.style.height = 'auto';

  appendMessage('user', message, null, images);
  lastUserMessage = message;
  clearAttachments();
  await getAnswer(message, images);
}

function stopGenerating() {
  if (abortController) {
    aborted = true;
    try { abortController.abort(); } catch (e) {}
  }
}

function setGenerating(on) {
  const btn = document.getElementById('send-btn');
  if (!btn) return;
  if (on) {
    btn.textContent = '\u23F9';      // stop square
    btn.title = 'Stop generating';
    btn.classList.add('generating');
  } else {
    btn.textContent = '\u27A4';      // send arrow
    btn.title = 'Send';
    btn.classList.remove('generating');
  }
}

function regenerate() {
  if (isLoading || !lastUserMessage) return;
  getAnswer(lastUserMessage);
}

// Show a "Regenerate" action on the last assistant message only (re-asks
// the last user message and replaces that reply).
function updateRegenerateButton() {
  document.querySelectorAll('#messages .regenerate-btn').forEach(b => b.remove());
  if (isLoading || !lastUserMessage) return;
  const messages = document.querySelectorAll('#messages .message');
  if (!messages.length) return;
  const last = messages[messages.length - 1];
  if (!last.classList.contains('assistant')) return;
  const actions = last.querySelector('.message-actions');
  if (!actions) return;

  const btn = document.createElement('button');
  btn.className = 'msg-action-btn regenerate-btn';
  btn.type = 'button';
  btn.textContent = '🔄 Regenerate';
  btn.addEventListener('click', () => {
    if (isLoading) return;
    last.remove();
    regenerate();
  });
  actions.appendChild(btn);
}

async function getAnswer(message, images) {
  isLoading = true;
  aborted = false;
  abortController = new AbortController();
  setGenerating(true);
  const typingId = showTyping();

  const hasImages = images && images.length > 0;
  let handled = false;
  try {
    handled = await streamAnswer(message, typingId, images);
  } catch (e) {
    handled = false;
  }
  if (!handled && !aborted) {
    if (hasImages) {
      removeTyping(typingId);
      appendMessage('assistant', 'Sorry, I could not process the image(s). Please try again.');
    } else {
      await nonStreamAnswer(message, typingId);
    }
  } else if (!handled && aborted) {
    removeTyping(typingId);
  }

  isLoading = false;
  abortController = null;
  setGenerating(false);
  updateRegenerateButton();
  refreshConversationList();
}

// Streaming path (Server-Sent Events). Returns true if it rendered something,
// false if it failed before rendering (so the caller falls back).
async function streamAnswer(message, typingId, images) {
  let res;
  try {
    res = await fetch(`${API}/api/chat/stream`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ message, mode: 'auto', images: (images && images.length) ? images : null, conversation_id: currentConversationId }),
      signal: abortController ? abortController.signal : undefined
    });
  } catch (e) {
    return false;
  }
  if (!res.ok || !res.body) return false;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let raw = '';
  let refs = null;
  let started = false;
  let mode = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }

        if (evt.type === 'meta') {
          mode = evt.mode;
          if (evt.conversation_id) currentConversationId = evt.conversation_id;
          removeTyping(typingId);
          refs = startAssistantBubble(mode);
          started = true;
        } else if (evt.type === 'chunk') {
          if (!refs) { removeTyping(typingId); refs = startAssistantBubble(mode); started = true; }
          raw += evt.text;
          refs.md.innerHTML = renderMarkdown(raw);
          scrollChat();
        } else if (evt.type === 'error') {
          if (!started) return false;
          raw += (raw ? '\n\n' : '') + 'Error: ' + (evt.message || 'something went wrong');
          if (refs) refs.md.innerHTML = renderMarkdown(raw);
        }
      }
    }
  } catch (e) {
    if (!started) return false;
  }

  if (!started) return false;
  if (refs) {
    refs.md.innerHTML = renderMarkdown(raw);
    finalizeAssistantBubble(refs, raw);
  }
  return true;
}

// Non-streaming fallback (original behaviour).
async function nonStreamAnswer(message, typingId) {
  try {
    const res = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ message, mode: 'auto', conversation_id: currentConversationId })
    });
    const data = await res.json();
    removeTyping(typingId);
    if (res.ok) {
      appendMessage('assistant', data.response, data.mode);
    } else {
      appendMessage('assistant', `Error: ${data.detail || 'Something went wrong.'}`);
    }
  } catch (e) {
    removeTyping(typingId);
    appendMessage('assistant', 'Connection error. Please check the server.');
  }
}

function scrollChat() {
  const c = document.querySelector('.chat-messages-container');
  if (c) c.scrollTop = c.scrollHeight;
}

// Build an empty assistant bubble we can stream into; returns DOM refs.
function startAssistantBubble(mode) {
  const container = document.getElementById('messages');
  const empty = container.querySelector('.empty-state');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = 'message assistant';

  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.textContent = '\uD83E\uDDE0';

  const body = document.createElement('div');
  body.className = 'message-body';

  const contentEl = document.createElement('div');
  contentEl.className = 'message-content';

  if (mode && mode !== 'auto' && mode !== 'general') {
    const modeIcons = { rag: '\uD83D\uDCC4', web: '\uD83C\uDF10', sql: '\uD83D\uDDC4\uFE0F', code: '\uD83D\uDCBB', vision: '\uD83D\uDDBC\uFE0F' };
    const modeNames = { rag: 'Document Chat', web: 'Web Search', sql: 'SQL Query', code: 'Code Execution', vision: 'Image' };
    const badge = document.createElement('div');
    badge.className = 'tool-badge';
    badge.innerHTML = `<span>${modeIcons[mode] || '\uD83E\uDDE0'}</span> ${modeNames[mode] || 'Tool'}`;
    contentEl.appendChild(badge);
  }

  const md = document.createElement('div');
  md.className = 'md';
  contentEl.appendChild(md);
  body.appendChild(contentEl);

  const timeEl = document.createElement('div');
  timeEl.className = 'message-time';
  timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  body.appendChild(timeEl);

  div.appendChild(avatar);
  div.appendChild(body);
  container.appendChild(div);
  scrollChat();

  return { md, contentEl, body, timeEl };
}

function finalizeAssistantBubble(refs, rawText) {
  enhanceCodeBlocks(refs.md);
  renderMath(refs.md);
  const actions = buildActions(rawText, refs.contentEl);
  refs.body.insertBefore(actions, refs.timeEl);
}

// ===== Rendering helpers =====
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function renderMarkdown(text) {
  if (window.marked && window.DOMPurify) {
    try {
      // Protect LaTeX math (\\[..\\], $$..$$, \\(..\\)) from markdown mangling
      // by swapping each segment for a placeholder, then restoring it after.
      const math = [];
      let src = String(text);
      const patterns = [/\$\$[\s\S]+?\$\$/g, /\\\[[\s\S]+?\\\]/g, /\\\([\s\S]+?\\\)/g];
      for (const p of patterns) {
        src = src.replace(p, (m) => {
          const tok = `@@MATH${math.length}@@`;
          math.push(m);
          return tok;
        });
      }
      let html = window.marked.parse(src, { breaks: true, gfm: true });
      html = window.DOMPurify.sanitize(html);
      html = html.replace(/@@MATH(\d+)@@/g, (m, i) => escapeHtml(math[Number(i)] || ''));
      return html;
    } catch (e) { /* fall through */ }
  }
  return escapeHtml(text).replace(/\n/g, '<br>');
}

function renderMath(el) {
  if (window.renderMathInElement) {
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '\\[', right: '\\]', display: true },
          { left: '\\(', right: '\\)', display: false }
        ],
        throwOnError: false,
        strict: 'ignore'
      });
    } catch (e) {}
  }
}

function looksLikeHtml(codeText, codeEl) {
  const cls = (codeEl && codeEl.className) || '';
  if (/language-(html|xml|xhtml|svg|markup)/i.test(cls)) return true;
  const t = (codeText || '').trim().toLowerCase();
  if (t.includes('<!doctype html') || t.includes('<html') || t.includes('<svg')) return true;
  return /^<(div|section|main|body|head|style|h[1-6]|p|ul|ol|table|canvas|form|button|span|a|img)\b/.test(t);
}

function enhanceCodeBlocks(scope) {
  scope.querySelectorAll('pre code').forEach(block => {
    if (window.hljs) {
      try { window.hljs.highlightElement(block); } catch (e) {}
    }
  });
  scope.querySelectorAll('pre').forEach(pre => {
    const code = pre.querySelector('code');
    const codeText = code ? code.innerText : pre.innerText;

    // Live preview button for HTML / SVG snippets
    if (code && looksLikeHtml(codeText, code) && !pre.querySelector('.code-preview-btn')) {
      const pbtn = document.createElement('button');
      pbtn.className = 'code-preview-btn';
      pbtn.type = 'button';
      pbtn.textContent = 'Preview';
      pbtn.addEventListener('click', () => openArtifact(codeText));
      pre.appendChild(pbtn);
    }

    // Copy button
    if (pre.querySelector('.code-copy-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'code-copy-btn';
    btn.type = 'button';
    btn.textContent = 'Copy';
    btn.addEventListener('click', () => {
      navigator.clipboard.writeText(codeText);
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
    });
    pre.appendChild(btn);
  });
}

// ===== Artifacts-style live preview (sandboxed iframe) =====
function ensureArtifactPanel() {
  if (document.getElementById('artifact-panel')) return;

  const overlay = document.createElement('div');
  overlay.className = 'artifact-overlay';
  overlay.id = 'artifact-overlay';
  overlay.addEventListener('click', closeArtifact);

  const panel = document.createElement('div');
  panel.className = 'artifact-panel';
  panel.id = 'artifact-panel';
  panel.innerHTML =
    '<div class="artifact-header">' +
      '<span class="artifact-title">Preview</span>' +
      '<div class="artifact-tabs">' +
        '<button class="artifact-tab active" data-tab="preview" type="button">Preview</button>' +
        '<button class="artifact-tab" data-tab="code" type="button">Code</button>' +
      '</div>' +
      '<button class="artifact-close" id="artifact-close" type="button">\u2715</button>' +
    '</div>' +
    '<div class="artifact-body">' +
      '<iframe class="artifact-frame" id="artifact-frame" sandbox="allow-scripts allow-modals"></iframe>' +
      '<pre class="artifact-code" id="artifact-code" style="display:none"></pre>' +
    '</div>';

  document.body.appendChild(overlay);
  document.body.appendChild(panel);

  panel.querySelector('#artifact-close').addEventListener('click', closeArtifact);
  panel.querySelectorAll('.artifact-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      panel.querySelectorAll('.artifact-tab').forEach(t => t.classList.toggle('active', t === tab));
      const showCode = tab.dataset.tab === 'code';
      panel.querySelector('#artifact-frame').style.display = showCode ? 'none' : 'block';
      panel.querySelector('#artifact-code').style.display = showCode ? 'block' : 'none';
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeArtifact();
  });
}

function openArtifact(codeText) {
  ensureArtifactPanel();
  const frame = document.getElementById('artifact-frame');
  const codeEl = document.getElementById('artifact-code');

  let html = codeText;
  const t = codeText.trim().toLowerCase();
  if (t.startsWith('<svg')) {
    html = '<!DOCTYPE html><html><head><meta charset="utf-8">' +
           '<style>body{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#fff}</style>' +
           '</head><body>' + codeText + '</body></html>';
  }
  frame.srcdoc = html;
  codeEl.textContent = codeText;

  document.querySelectorAll('.artifact-tab').forEach(t2 =>
    t2.classList.toggle('active', t2.dataset.tab === 'preview'));
  frame.style.display = 'block';
  codeEl.style.display = 'none';

  document.getElementById('artifact-overlay').classList.add('open');
  document.getElementById('artifact-panel').classList.add('open');
}

function closeArtifact() {
  const o = document.getElementById('artifact-overlay');
  const p = document.getElementById('artifact-panel');
  if (o) o.classList.remove('open');
  if (p) p.classList.remove('open');
  const frame = document.getElementById('artifact-frame');
  if (frame) frame.srcdoc = '';
}

function buildActions(rawText, contentEl) {
  const wrap = document.createElement('div');
  wrap.className = 'message-actions';

  const copyBtn = document.createElement('button');
  copyBtn.className = 'msg-action-btn';
  copyBtn.type = 'button';
  copyBtn.textContent = '\uD83D\uDCCB Copy';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(rawText);
    showToast('Copied to clipboard', 'success');
  });
  wrap.appendChild(copyBtn);

  const pdfBtn = document.createElement('button');
  pdfBtn.className = 'msg-action-btn';
  pdfBtn.type = 'button';
  pdfBtn.textContent = '\uD83D\uDCC4 Export PDF';
  pdfBtn.addEventListener('click', () => exportPdf(rawText));
  wrap.appendChild(pdfBtn);

  return wrap;
}

function buildUserActions(rawText, msgDiv) {
  const wrap = document.createElement('div');
  wrap.className = 'message-actions';

  const copyBtn = document.createElement('button');
  copyBtn.className = 'msg-action-btn';
  copyBtn.type = 'button';
  copyBtn.textContent = '\uD83D\uDCCB Copy';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(rawText);
    showToast('Copied to clipboard', 'success');
  });
  wrap.appendChild(copyBtn);

  const editBtn = document.createElement('button');
  editBtn.className = 'msg-action-btn';
  editBtn.type = 'button';
  editBtn.textContent = '\u270F\uFE0F Edit';
  editBtn.addEventListener('click', () => editUserMessage(rawText, msgDiv));
  wrap.appendChild(editBtn);

  return wrap;
}

function editUserMessage(rawText, msgDiv) {
  if (isLoading) stopGenerating();
  // Remove this message and every message after it.
  let el = msgDiv;
  const toRemove = [];
  while (el) { toRemove.push(el); el = el.nextElementSibling; }
  toRemove.forEach(n => n.remove());
  updateRegenerateButton();
  // Drop the edited text back into the input box for re-sending.
  const input = document.getElementById('chat-input');
  if (input) {
    input.value = rawText;
    input.focus();
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  }
}

function exportPdf(rawText) {
  if (!window.html2pdf) { showToast('PDF tool still loading, try again', 'warning'); return; }
  const wrapper = document.createElement('div');
  wrapper.style.cssText =
    'position:fixed;left:-10000px;top:0;width:800px;padding:28px;background:#ffffff;color:#111111;' +
    'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.6;';
  wrapper.innerHTML = renderMarkdown(rawText);
  renderMath(wrapper);
  wrapper.querySelectorAll('table').forEach(t => {
    t.style.borderCollapse = 'collapse'; t.style.width = '100%'; t.style.margin = '10px 0';
  });
  wrapper.querySelectorAll('th,td').forEach(c => {
    c.style.border = '1px solid #999'; c.style.padding = '6px'; c.style.textAlign = 'left';
  });
  wrapper.querySelectorAll('pre').forEach(p => {
    p.style.background = '#f4f4f4'; p.style.padding = '10px'; p.style.borderRadius = '6px';
    p.style.whiteSpace = 'pre-wrap'; p.style.color = '#111';
  });
  document.body.appendChild(wrapper);
  window.html2pdf()
    .set({ margin: 10, filename: 'kgpt-answer.pdf', html2canvas: { scale: 2 }, jsPDF: { unit: 'mm', format: 'a4' } })
    .from(wrapper)
    .save()
    .then(() => wrapper.remove())
    .catch(() => wrapper.remove());
}

// ===== Messages =====
function appendMessage(role, content, msgMode = null, imageUrls = null) {
  const container = document.getElementById('messages');

  const empty = container.querySelector('.empty-state');
  if (empty) empty.remove();

  if (role === 'user') lastUserMessage = content;

  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const div = document.createElement('div');
  div.className = `message ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.textContent = role === 'user' ? '\uD83D\uDC64' : '\uD83E\uDDE0';

  const body = document.createElement('div');
  body.className = 'message-body';

  const contentEl = document.createElement('div');
  contentEl.className = 'message-content';

  // Tool badge (assistant + specific tool)
  if (role === 'assistant' && msgMode && msgMode !== 'auto' && msgMode !== 'general') {
    const modeIcons = { rag: '\uD83D\uDCC4', web: '\uD83C\uDF10', sql: '\uD83D\uDDC4\uFE0F', code: '\uD83D\uDCBB', vision: '\uD83D\uDDBC\uFE0F' };
    const modeNames = { rag: 'Document Chat', web: 'Web Search', sql: 'SQL Query', code: 'Code Execution', vision: 'Image' };
    const badge = document.createElement('div');
    badge.className = 'tool-badge';
    badge.innerHTML = `<span>${modeIcons[msgMode] || '\uD83E\uDDE0'}</span> ${modeNames[msgMode] || 'Tool'}`;
    contentEl.appendChild(badge);
  }

  // Attached image(s) (user message)
  if (role === 'user' && imageUrls) {
    const arr = Array.isArray(imageUrls) ? imageUrls : [imageUrls];
    arr.forEach(src => {
      const img = document.createElement('img');
      img.className = 'message-image';
      img.src = src;
      contentEl.appendChild(img);
    });
  }

  const md = document.createElement('div');
  md.className = 'md';
  if (role === 'user') {
    md.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
  } else {
    md.innerHTML = renderMarkdown(content);
  }
  contentEl.appendChild(md);
  body.appendChild(contentEl);

  if (role === 'assistant') {
    body.appendChild(buildActions(content, contentEl));
  } else if (role === 'user') {
    body.appendChild(buildUserActions(content, div));
  }

  const timeEl = document.createElement('div');
  timeEl.className = 'message-time';
  timeEl.textContent = time;
  body.appendChild(timeEl);

  div.appendChild(avatar);
  div.appendChild(body);
  container.appendChild(div);

  if (role === 'assistant') { enhanceCodeBlocks(md); renderMath(md); }

  const scrollContainer = document.querySelector('.chat-messages-container');
  if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;

  updateRegenerateButton();
}

function showTyping() {
  const id = 'typing-' + Date.now();
  const container = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = id;
  div.innerHTML = `
    <div class="message-avatar">\uD83E\uDDE0</div>
    <div class="message-content">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  container.appendChild(div);

  const scrollContainer = document.querySelector('.chat-messages-container');
  if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ===== Conversations (sidebar) =====
function emptyStateHtml() {
  return `
    <div class="empty-state">
      <div class="big-icon">\uD83E\uDDE0</div>
      <h3>Welcome to kGPT</h3>
      <p>One clean input box. kGPT automatically decides which tool to run based on your prompt.</p>
    </div>
  `;
}

async function loadConversations() {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { headers: authHeaders() });
    if (!res.ok) return;
    let convs = await res.json();
    if (!convs.length) {
      const c = await createConversationApi();
      convs = c ? [c] : [];
    }
    renderConversations(convs);
    if (!currentConversationId || !convs.find(c => c.id === currentConversationId)) {
      currentConversationId = convs[0] ? convs[0].id : null;
    }
    highlightActiveConversation();
    if (currentConversationId) await loadConversationMessages(currentConversationId);
  } catch (e) {}
}

async function refreshConversationList() {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { headers: authHeaders() });
    if (!res.ok) return;
    renderConversations(await res.json());
    highlightActiveConversation();
  } catch (e) {}
}

function renderConversations(convs) {
  const list = document.getElementById('conv-list');
  if (!list) return;
  list.innerHTML = '';
  convs.forEach(c => {
    const item = document.createElement('div');
    item.className = 'conv-item';
    item.dataset.id = c.id;

    const title = document.createElement('span');
    title.className = 'conv-title';
    title.textContent = c.title || 'New chat';
    title.title = 'Double-click to rename';
    title.addEventListener('dblclick', (e) => { e.stopPropagation(); startRename(item, c.id, title); });

    const del = document.createElement('button');
    del.className = 'conv-del';
    del.type = 'button';
    del.textContent = '\u2715';
    del.title = 'Delete conversation';
    del.addEventListener('click', (e) => { e.stopPropagation(); deleteConversation(c.id); });

    item.appendChild(title);
    item.appendChild(del);
    item.addEventListener('click', () => switchConversation(c.id));
    list.appendChild(item);
  });
  highlightActiveConversation();
}

function highlightActiveConversation() {
  document.querySelectorAll('#conv-list .conv-item').forEach(el =>
    el.classList.toggle('active', Number(el.dataset.id) === currentConversationId));
}

async function switchConversation(id) {
  if (isLoading) stopGenerating();
  currentConversationId = id;
  if (typeof showView === 'function') showView('chat');
  highlightActiveConversation();
  await loadConversationMessages(id);
}

async function loadConversationMessages(id) {
  const container = document.getElementById('messages');
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}/messages`, { headers: authHeaders() });
    if (!res.ok) { container.innerHTML = emptyStateHtml(); return; }
    const msgs = await res.json();
    container.innerHTML = '';
    if (!msgs.length) { container.innerHTML = emptyStateHtml(); return; }
    msgs.forEach(m => appendMessage(m.role, m.content, m.mode || null));
  } catch (e) {
    container.innerHTML = emptyStateHtml();
  }
}

async function createConversationApi() {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { method: 'POST', headers: authHeaders() });
    if (res.ok) return await res.json();
  } catch (e) {}
  return null;
}

async function newConversation() {
  const c = await createConversationApi();
  if (!c) { showToast('Could not create chat', 'error'); return; }
  currentConversationId = c.id;
  if (typeof showView === 'function') showView('chat');
  document.getElementById('messages').innerHTML = emptyStateHtml();
  await refreshConversationList();
  const input = document.getElementById('chat-input');
  if (input) input.focus();
}

async function deleteConversation(id) {
  if (!confirm('Delete this conversation?')) return;
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}`, { method: 'DELETE', headers: authHeaders() });
    if (!res.ok) { showToast('Delete failed', 'error'); return; }
  } catch (e) { showToast('Delete failed', 'error'); return; }
  if (id === currentConversationId) currentConversationId = null;
  await loadConversations();
  showToast('Conversation deleted', 'success');
}

function startRename(item, id, titleSpan) {
  const current = titleSpan.textContent;
  const input = document.createElement('input');
  input.className = 'conv-rename-input';
  input.value = current;
  titleSpan.replaceWith(input);
  input.focus();
  input.select();

  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const val = input.value.trim();
    const span = document.createElement('span');
    span.className = 'conv-title';
    span.title = 'Double-click to rename';
    span.textContent = (save && val) ? val : current;
    if (input.parentNode) input.replaceWith(span);
    span.addEventListener('dblclick', (e) => { e.stopPropagation(); startRename(item, id, span); });
    if (save && val && val !== current) await renameConversation(id, val);
  };

  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

async function renameConversation(id, title) {
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ title })
    });
    if (!res.ok) { showToast('Rename failed', 'error'); return; }
    refreshConversationList();
  } catch (e) {
    showToast('Rename failed', 'error');
  }
}

// ===== History =====
async function loadHistory() {
  try {
    const res = await fetch(`${API}/api/chat/history`, { headers: authHeaders() });
    if (!res.ok) return;
    const messages = await res.json();
    if (messages.length === 0) return;

    const container = document.getElementById('messages');
    container.innerHTML = '';
    messages.forEach(msg => {
      appendMessage(msg.role, msg.content, msg.mode || null);
    });
  } catch (e) {}
}

async function clearHistory() {
  if (!confirm('Clear ALL chat history across every conversation? This cannot be undone.')) return;
  try {
    const res = await fetch(`${API}/api/chat/history`, { method: 'DELETE', headers: authHeaders() });
    if (!res.ok) { showToast('Failed to clear history', 'error'); return; }
    lastUserMessage = null;
    document.getElementById('messages').innerHTML = `
      <div class="empty-state">
        <div class="big-icon">\uD83E\uDDE0</div>
        <h3>Chat cleared</h3>
        <p>Start a new conversation below</p>
      </div>
    `;
    updateRegenerateButton();
    showToast('Chat history cleared', 'success');
  } catch (e) {
    showToast('Failed to clear history', 'error');
  }
}

// ===== Attach (images -> vision, documents -> knowledge base) =====
function initImage() {
  const fileInput = document.getElementById('image-input');
  if (!fileInput) return;
  fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    files.forEach(handleAttachedFile);
  });
}

function handleAttachedFile(file) {
  if (file.type.startsWith('image/')) {
    if (pendingImages.length >= MAX_IMAGES) { showToast(`Up to ${MAX_IMAGES} images per message`, 'warning'); return; }
    if (file.size > 4 * 1024 * 1024) { showToast(`${file.name}: image too large (max 4MB)`, 'warning'); return; }
    const reader = new FileReader();
    reader.onload = () => { pendingImages.push(reader.result); addImageChip(reader.result); };
    reader.readAsDataURL(file);
  } else {
    uploadDocument(file);
  }
}

async function uploadDocument(file) {
  const chip = addDocChip(file.name, 'uploading...');
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${API}/api/documents/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token()}` },
      body: fd
    });
    if (res.ok) {
      updateDocChip(chip, file.name, 'ready \u2014 ask about it', false);
      showToast('Document added to knowledge base', 'success');
    } else {
      let detail = 'upload failed';
      try { const d = await res.json(); detail = d.detail || detail; } catch (e) {}
      updateDocChip(chip, file.name, detail, true);
      showToast('Upload failed', 'error');
    }
  } catch (e) {
    updateDocChip(chip, file.name, 'upload failed', true);
    showToast('Upload error', 'error');
  }
}

function chipsContainer() {
  return document.querySelector('.input-container-centered');
}

function addImageChip(dataUrl) {
  const container = chipsContainer();
  if (!container) return;
  const chip = document.createElement('div');
  chip.className = 'image-chip';
  const img = document.createElement('img');
  img.src = dataUrl;
  const label = document.createElement('span');
  label.textContent = 'Image';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'image-chip-remove';
  remove.textContent = '\u2715';
  remove.title = 'Remove image';
  remove.addEventListener('click', () => {
    const i = pendingImages.indexOf(dataUrl);
    if (i >= 0) pendingImages.splice(i, 1);
    chip.remove();
  });
  chip.appendChild(img);
  chip.appendChild(label);
  chip.appendChild(remove);
  container.insertBefore(chip, container.firstChild);
}

function addDocChip(name, status) {
  const container = chipsContainer();
  if (!container) return null;
  const chip = document.createElement('div');
  chip.className = 'image-chip';
  const icon = document.createElement('span');
  icon.textContent = '\uD83D\uDCC4';
  const label = document.createElement('span');
  label.className = 'doc-chip-label';
  label.textContent = `${name} \u2014 ${status}`;
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'image-chip-remove';
  remove.textContent = '\u2715';
  remove.title = 'Dismiss';
  remove.addEventListener('click', () => chip.remove());
  chip.appendChild(icon);
  chip.appendChild(label);
  chip.appendChild(remove);
  container.insertBefore(chip, container.firstChild);
  return chip;
}

function updateDocChip(chip, name, status, error) {
  if (!chip) return;
  const label = chip.querySelector('.doc-chip-label');
  if (label) label.textContent = `${name} \u2014 ${status}`;
  chip.style.opacity = error ? '0.7' : '1';
}

function clearAttachments() {
  pendingImages = [];
  const container = chipsContainer();
  if (container) container.querySelectorAll('.image-chip').forEach(c => c.remove());
}

// ===== Input Auto-resize =====
function initInput() {
  const input = document.getElementById('chat-input');
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
}

// ===== Toast =====
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { success: '\u2705', error: '\u274C', warning: '\u26A0\uFE0F' };
  toast.innerHTML = `<span>${icons[type] || ''}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ===== Logout =====
function logout() {
  localStorage.removeItem('kgpt_token');
  window.location.href = '/login.html';
}

// ===== Run =====
document.addEventListener('DOMContentLoaded', () => {
  init();
  initInput();
  initImage();
});