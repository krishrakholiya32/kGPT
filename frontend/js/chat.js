/* ===== kGPT Chat Logic ===== */

const API = '';
const token = () => localStorage.getItem('kgpt_token');

// Works on both HTTP and HTTPS
function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(() => _fallbackCopy(text));
  } else {
    _fallbackCopy(text);
  }
}
function _fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { document.execCommand('copy'); } catch {}
  document.body.removeChild(ta);
}

let isLoading = false;
let currentUser = null;
let lastUserMessage = null;
let abortController = null;
let aborted = false;
let currentConversationId = null;
let conversationsCache = [];
let currentConversationHasAttachment = false;
let currentConversationHasMessages = false;
let uploadInProgress = false;

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

// ===== Mobile Sidebar =====
function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('open');
}
function closeSidebar() {
  document.querySelector('.sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('open');
}

// ===== Send Message =====
async function sendMessage() {
  if (isLoading) { stopGenerating(); return; }
  if (uploadInProgress) { showToast('Please wait — file is still uploading', 'warning'); return; }
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;

  input.value = '';
  input.style.height = 'auto';

  currentConversationHasMessages = true;
  _saveConvSession(currentConversationId);
  appendMessage('user', message);
  lastUserMessage = message;
  await getAnswer(message);
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

async function getAnswer(message) {
  isLoading = true;
  aborted = false;
  abortController = new AbortController();
  setGenerating(true);
  const typingId = showTyping();

  let handled = false;
  try {
    handled = await streamAnswer(message, typingId);
  } catch (e) {
    handled = false;
  }
  if (!handled && !aborted) {
    await nonStreamAnswer(message, typingId);
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
async function streamAnswer(message, typingId) {
  let res;
  try {
    res = await fetch(`${API}/api/chat/stream`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ message, mode: 'auto', conversation_id: currentConversationId }),
      signal: abortController ? abortController.signal : undefined
    });
  } catch (e) {
    return false;
  }
  if (!res.ok) {
    if (res.status === 429) {
      const data = await res.json().catch(() => ({}));
      removeTyping(typingId);
      appendMessage('assistant', `⚠️ ${data.detail || 'Too many requests — please wait a moment.'}`);
      return true; // handled — don't fall through to nonStream
    }
    return false;
  }
  if (!res.body) return false;

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
    const modeIcons = { web: '\uD83C\uDF10' };
    const modeNames = { web: 'Web Search' };
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
      copyToClipboard(codeText);
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
    copyToClipboard(rawText);
    showToast('Copied to clipboard', 'success');
  });
  wrap.appendChild(copyBtn);

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
    copyToClipboard(rawText);
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


// ===== Messages =====
function appendMessage(role, content, msgMode = null) {
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
    const modeIcons = { web: '\uD83C\uDF10' };
    const modeNames = { web: 'Web Search' };
    const badge = document.createElement('div');
    badge.className = 'tool-badge';
    badge.innerHTML = `<span>${modeIcons[msgMode] || '\uD83E\uDDE0'}</span> ${modeNames[msgMode] || 'Tool'}`;
    contentEl.appendChild(badge);
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
      <p>One clean input box. kGPT automatically decides whether to answer directly or search the web.</p>
      <div class="suggestions-grid">
        <div class="suggestion-card" onclick="useHint('Search for the latest AI news')">
          <div class="suggestion-icon">\uD83C\uDF10</div>
          <div class="suggestion-title">Web Search</div>
          <div class="suggestion-text">"Search for the latest AI news"</div>
        </div>
        <div class="suggestion-card" onclick="useHint('Explain how neural networks work')">
          <div class="suggestion-icon">\uD83E\uDDE0</div>
          <div class="suggestion-title">General Chat</div>
          <div class="suggestion-text">"Explain how neural networks work"</div>
        </div>
        <div class="suggestion-card" onclick="triggerFileInput()">
          <div class="suggestion-icon">\uD83D\uDCCE</div>
          <div class="suggestion-title">Documents</div>
          <div class="suggestion-text">Attach PDF, DOCX, or images</div>
        </div>
      </div>
    </div>
  `;
}

async function loadConversations() {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { headers: authHeaders() });
    if (!res.ok) return;
    let convs = await res.json();

    // Silently delete conversations with no messages AND no attachments (left over from previous sessions).
    const empties = convs.filter(c => (c.message_count || 0) === 0 && !(c.attachment_names && c.attachment_names.length));
    await Promise.all(empties.map(c => _deleteConversationSilent(c.id)));
    convs = convs.filter(c => (c.message_count || 0) > 0 || (c.attachment_names && c.attachment_names.length));

    // If there's a saved conversation from a page refresh, restore it.
    const savedId = parseInt(sessionStorage.getItem('kgpt_conv') || '0');
    const savedConv = savedId ? convs.find(c => c.id === savedId) : null;

    if (savedConv) {
      conversationsCache = convs;
      renderConversations(convs);
      currentConversationId = savedId;
      currentConversationHasMessages = (savedConv.message_count || 0) > 0;
      currentConversationHasAttachment = !!(savedConv.attachment_names && savedConv.attachment_names.length);
      highlightActiveConversation();
      await loadConversationMessages(savedId);
    } else {
      // Fresh start — create a new empty conversation.
      const fresh = await createConversationApi();
      if (fresh) convs.unshift(fresh);
      conversationsCache = convs;
      renderConversations(convs);
      currentConversationId = fresh ? fresh.id : (convs[0] ? convs[0].id : null);
      currentConversationHasMessages = false;
      currentConversationHasAttachment = false;
      highlightActiveConversation();
      document.getElementById('messages').innerHTML = emptyStateHtml();
    }
  } catch (e) {}
}

async function refreshConversationList() {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { headers: authHeaders() });
    if (!res.ok) return;
    conversationsCache = await res.json();
    renderConversations(conversationsCache);
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
    item.addEventListener('click', () => { switchConversation(c.id); closeSidebar(); });
    list.appendChild(item);
  });
  highlightActiveConversation();
}

function highlightActiveConversation() {
  document.querySelectorAll('#conv-list .conv-item').forEach(el =>
    el.classList.toggle('active', Number(el.dataset.id) === currentConversationId));
}

async function switchConversation(id) {
  if (id === currentConversationId) return;
  if (isLoading) stopGenerating();

  // Drop the current conversation if it never got any messages and has no attachments.
  if (currentConversationId && !currentConversationHasMessages && !currentConversationHasAttachment) {
    await _deleteConversationSilent(currentConversationId);
    conversationsCache = conversationsCache.filter(c => c.id !== currentConversationId);
  }

  currentConversationId = id;
  currentConversationHasMessages = false;
  const conv = conversationsCache.find(c => c.id === id);
  currentConversationHasAttachment = !!(conv && conv.attachment_names && conv.attachment_names.length);
  _saveConvSession(id);
  highlightActiveConversation();
  await loadConversationMessages(id);
}

async function loadConversationMessages(id) {
  const container = document.getElementById('messages');
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}/messages`, { headers: authHeaders() });
    if (!res.ok) { container.innerHTML = emptyStateHtml(); currentConversationHasMessages = false; return; }
    const msgs = await res.json();
    container.innerHTML = '';
    currentConversationHasMessages = msgs.length > 0;

    // If this conversation has attachments, show a note so the user knows context is active.
    const conv = conversationsCache.find(c => c.id === id);
    if (conv && conv.attachment_names && conv.attachment_names.length) {
      const label = conv.attachment_names.join(', ');
      addSystemNote(`📎 ${label} · context active for this conversation`);
    }

    if (!msgs.length) { container.innerHTML += emptyStateHtml(); return; }
    msgs.forEach(m => appendMessage(m.role, m.content, m.mode || null));
  } catch (e) {
    container.innerHTML = emptyStateHtml();
    currentConversationHasMessages = false;
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
  // Drop the current conversation only if it has no messages and no attachments.
  if (currentConversationId && !currentConversationHasMessages && !currentConversationHasAttachment) {
    await _deleteConversationSilent(currentConversationId);
    conversationsCache = conversationsCache.filter(c => c.id !== currentConversationId);
  }

  const c = await createConversationApi();
  if (!c) { showToast('Could not create chat', 'error'); return; }
  currentConversationId = c.id;
  currentConversationHasMessages = false;
  currentConversationHasAttachment = false;
  _saveConvSession(null);
  conversationsCache.unshift(c);
  renderConversations(conversationsCache);
  highlightActiveConversation();
  document.getElementById('messages').innerHTML = emptyStateHtml();
  const input = document.getElementById('chat-input');
  if (input) input.focus();
}

async function _deleteConversationSilent(id) {
  try {
    await fetch(`${API}/api/chat/conversations/${id}`, { method: 'DELETE', headers: authHeaders() });
  } catch (e) {}
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

// ===== Session conv persistence =====
function _saveConvSession(id) {
  if (id) sessionStorage.setItem('kgpt_conv', String(id));
  else sessionStorage.removeItem('kgpt_conv');
}

// ===== Logout =====
function logout() {
  localStorage.removeItem('kgpt_token');
  sessionStorage.removeItem('kgpt_conv');
  window.location.href = '/login.html';
}

// ===== File Attachment =====
function addSystemNote(text) {

  const container = document.getElementById('messages');
  if (!container) return;
  const empty = container.querySelector('.empty-state');
  if (empty) empty.remove();
  const div = document.createElement('div');
  div.className = 'system-note';
  div.textContent = text;
  container.appendChild(div);
  scrollChat();
}


function triggerFileInput() {
  if (!currentConversationId) {
    showToast('Start a conversation first', 'warning');
    return;
  }
  const fi = document.getElementById('file-input');
  if (fi) fi.click();
}

async function handleFileSelect(event) {
  const files = Array.from(event.target.files);
  if (!files.length) return;
  event.target.value = '';

  uploadInProgress = true;

  for (const file of files) {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${API}/api/chat/conversations/${currentConversationId}/attachment`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token()}` },
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showToast(`${file.name}: ${data.detail || 'Upload failed'}`, 'error');
        if (res.status === 400) break; // hit the 10-file limit
        continue;
      }
      const data = await res.json();
      currentConversationHasAttachment = true;
      _saveConvSession(currentConversationId);
      const cached = conversationsCache.find(c => c.id === currentConversationId);
      if (cached) {
        if (!cached.attachment_names) cached.attachment_names = [];
        cached.attachment_names.push(data.filename);
      }
      addSystemNote(`📎 ${data.filename} attached — ask me anything about it. Context stays active for this entire conversation.`);
    } catch (e) {
      showToast(`${file.name}: upload failed`, 'error');
    }
  }

  uploadInProgress = false;
}


// ===== Run =====
document.addEventListener('DOMContentLoaded', () => {
  init();
  initInput();
});

// Force a fresh load if the browser restores this page from bfcache (e.g. after logout → login → back).
window.addEventListener('pageshow', (e) => {
  if (e.persisted) window.location.reload();
});