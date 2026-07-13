import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ArtifactProvider } from '../components/Artifact'
import DocumentPanel from '../components/DocumentPanel'
import Markdown from '../components/Markdown'
import { showToast } from '../components/Toast'
import { copyToClipboard } from '../lib/clipboard'
import * as api from '../api/client'
import type { Conversation } from '../api/client'

type Role = 'user' | 'assistant' | 'system'
interface Item {
  uid: number
  role: Role
  content: string
  mode: string | null
  sources?: string[] | null
}

let _uid = 0
const nextUid = () => ++_uid

function nowTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function Chat() {
  const navigate = useNavigate()
  const { logout: authLogout } = useAuth()

  const [username, setUsername] = useState('Loading...')
  const [items, setItems] = useState<Item[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationIdState] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [typing, setTyping] = useState(false)
  const [light, setLight] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarTab, setSidebarTab] = useState<'chats' | 'documents'>('chats')
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const [input, setInput] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingValue, setEditingValue] = useState('')

  // Refs mirroring the original module-level mutable state, so async streaming
  // callbacks always read current values.
  const convIdRef = useRef<number | null>(null)
  const hasMessagesRef = useRef(false)
  // Tracks whether the current conversation has a chat-scoped document, so the
  // empty-conversation auto-cleanup below doesn't sweep it away (and cascade-
  // delete the document with it) just because no chat messages were sent yet.
  const hasDocumentRef = useRef(false)
  const uploadInProgressRef = useRef(false)
  const isLoadingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  const abortedRef = useRef(false)
  const lastUserMessageRef = useRef<string | null>(null)
  const conversationsRef = useRef<Conversation[]>([])
  const assistantUidRef = useRef<number | null>(null)
  const rawRef = useRef('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    conversationsRef.current = conversations
  }, [conversations])
  useEffect(() => {
    isLoadingRef.current = isLoading
  }, [isLoading])

  const setConv = useCallback((id: number | null) => {
    convIdRef.current = id
    setCurrentConversationIdState(id)
  }, [])

  function saveConvSession(id: number | null) {
    if (id) sessionStorage.setItem('kgpt_conv', String(id))
    else sessionStorage.removeItem('kgpt_conv')
  }

  const scrollChat = useCallback(() => {
    const c = scrollRef.current
    if (c) c.scrollTop = c.scrollHeight
  }, [])

  useEffect(() => {
    scrollChat()
  }, [items, typing, scrollChat])

  // ── Theme ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const saved = localStorage.getItem('kgpt_theme') || 'dark'
    setLight(saved === 'light')
  }, [])
  useEffect(() => {
    document.body.classList.toggle('light-theme', light)
  }, [light])
  function toggleTheme() {
    setLight((v) => {
      const nv = !v
      localStorage.setItem('kgpt_theme', nv ? 'light' : 'dark')
      return nv
    })
  }

  // ── Sidebar (desktop collapse + mobile) ──────────────────────────────────────
  useEffect(() => {
    if (localStorage.getItem('kgpt_sidebar_collapsed') === '1') setCollapsed(true)
  }, [])
  function toggleDesktopSidebar() {
    setCollapsed((c) => {
      const nc = !c
      localStorage.setItem('kgpt_sidebar_collapsed', nc ? '1' : '')
      return nc
    })
  }
  const closeSidebar = () => setSidebarOpen(false)

  // ── Mobile viewport height fix (keyboard / browser chrome) ───────────────────
  useEffect(() => {
    const setAppHeight = () => {
      const h = window.visualViewport ? window.visualViewport.height : window.innerHeight
      const hpx = h + 'px'
      document.documentElement.style.setProperty('--app-h', hpx)
      const c = scrollRef.current
      if (c) c.scrollTop = c.scrollHeight
    }
    setAppHeight()
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', setAppHeight)
      window.visualViewport.addEventListener('scroll', setAppHeight)
      return () => {
        window.visualViewport?.removeEventListener('resize', setAppHeight)
        window.visualViewport?.removeEventListener('scroll', setAppHeight)
      }
    }
    window.addEventListener('resize', setAppHeight)
    return () => window.removeEventListener('resize', setAppHeight)
  }, [])

  // Force a fresh load if the browser restores this page from bfcache.
  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.location.reload()
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [])

  // ── Logout ───────────────────────────────────────────────────────────────────
  const logout = useCallback(() => {
    authLogout()
    navigate('/login')
  }, [authLogout, navigate])

  // ── Init: load user + conversations ──────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await api.apiMe()
        if (!res.ok) return logout()
        const user = await res.json()
        if (cancelled) return
        setUsername(user.username)
      } catch {
        return logout()
      }
      await loadConversations()
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── System notes + message helpers ───────────────────────────────────────────
  function addSystemNote(text: string) {
    setItems((prev) => [...prev, { uid: nextUid(), role: 'system', content: text, mode: null }])
  }
  function appendMessage(role: Role, content: string, mode: string | null = null, sources: string[] | null = null) {
    if (role === 'user') lastUserMessageRef.current = content
    setItems((prev) => [...prev, { uid: nextUid(), role, content, mode, sources }])
  }

  // ── Conversations ────────────────────────────────────────────────────────────
  async function loadConversations() {
    try {
      let convs = await api.listConversations()
      const isEmpty = (c: Conversation) =>
        (c.message_count || 0) === 0 &&
        !(c.attachment_names && c.attachment_names.length) &&
        !c.document_count
      const empties = convs.filter(isEmpty)
      await Promise.all(empties.map((c) => api.deleteConversationSilent(c.id)))
      convs = convs.filter((c) => !isEmpty(c))

      const savedId = parseInt(sessionStorage.getItem('kgpt_conv') || '0')
      const savedConv = savedId ? convs.find((c) => c.id === savedId) : null

      if (savedConv) {
        setConversations(convs)
        conversationsRef.current = convs
        setConv(savedId)
        hasMessagesRef.current = (savedConv.message_count || 0) > 0
        hasDocumentRef.current = (savedConv.document_count || 0) > 0
        await loadConversationMessages(savedId)
      } else {
        const fresh = await api.createConversation()
        if (fresh) convs.unshift(fresh)
        setConversations(convs)
        conversationsRef.current = convs
        setConv(fresh ? fresh.id : convs[0] ? convs[0].id : null)
        hasMessagesRef.current = false
        hasDocumentRef.current = false
        setItems([])
      }
    } catch {
      /* ignore */
    }
  }

  async function refreshConversationList() {
    try {
      const convs = await api.listConversations()
      setConversations(convs)
      conversationsRef.current = convs
    } catch {
      /* ignore */
    }
  }

  async function loadConversationMessages(id: number) {
    try {
      const msgs = await api.getMessages(id)
      const next: Item[] = []
      const conv = conversationsRef.current.find((c) => c.id === id)
      if (conv && conv.attachment_names && conv.attachment_names.length) {
        next.push({
          uid: nextUid(),
          role: 'system',
          content: `📎 ${conv.attachment_names.join(', ')} · context active for this conversation`,
          mode: null,
        })
      }
      for (const m of msgs) {
        next.push({ uid: nextUid(), role: m.role as Role, content: m.content, mode: m.mode, sources: m.sources })
      }
      hasMessagesRef.current = msgs.length > 0
      hasDocumentRef.current = (conv?.document_count || 0) > 0
      if (msgs.length) lastUserMessageRef.current = [...msgs].reverse().find((m) => m.role === 'user')?.content ?? null
      setItems(next)
    } catch {
      hasMessagesRef.current = false
      setItems([])
    }
  }

  async function switchConversation(id: number) {
    if (id === convIdRef.current) return
    if (isLoadingRef.current) stopGenerating()
    if (convIdRef.current && !hasMessagesRef.current && !hasDocumentRef.current) {
      await api.deleteConversationSilent(convIdRef.current)
      const filtered = conversationsRef.current.filter((c) => c.id !== convIdRef.current)
      setConversations(filtered)
      conversationsRef.current = filtered
    }
    setConv(id)
    hasMessagesRef.current = false
    hasDocumentRef.current = false
    saveConvSession(id)
    closeSidebar()
    await loadConversationMessages(id)
  }

  async function newConversation() {
    if (convIdRef.current && !hasMessagesRef.current && !hasDocumentRef.current) {
      await api.deleteConversationSilent(convIdRef.current)
      const filtered = conversationsRef.current.filter((c) => c.id !== convIdRef.current)
      setConversations(filtered)
      conversationsRef.current = filtered
    }
    const c = await api.createConversation()
    if (!c) {
      showToast('Could not create chat', 'error')
      return
    }
    setConv(c.id)
    hasMessagesRef.current = false
    hasDocumentRef.current = false
    saveConvSession(null)
    const next = [c, ...conversationsRef.current]
    setConversations(next)
    conversationsRef.current = next
    setItems([])
    textareaRef.current?.focus()
  }

  async function deleteConversation(id: number) {
    if (!window.confirm('Delete this conversation?')) return
    const ok = await api.deleteConversation(id)
    if (!ok) {
      showToast('Delete failed', 'error')
      return
    }
    if (id === convIdRef.current) setConv(null)
    await loadConversations()
    showToast('Conversation deleted', 'success')
  }

  async function commitRename(id: number, title: string) {
    const ok = await api.renameConversation(id, title)
    if (!ok) {
      showToast('Rename failed', 'error')
      return
    }
    refreshConversationList()
  }

  // ── Streaming answer ─────────────────────────────────────────────────────────
  function stopGenerating() {
    if (abortRef.current) {
      abortedRef.current = true
      try {
        abortRef.current.abort()
      } catch {
        /* ignore */
      }
    }
  }

  function startAssistantBubble(mode: string | null) {
    const uid = nextUid()
    assistantUidRef.current = uid
    rawRef.current = ''
    setItems((prev) => [...prev, { uid, role: 'assistant', content: '', mode }])
  }
  function updateAssistantContent(text: string) {
    const uid = assistantUidRef.current
    if (uid == null) return
    setItems((prev) => prev.map((it) => (it.uid === uid ? { ...it, content: text } : it)))
  }
  function setAssistantSources(sources: string[]) {
    const uid = assistantUidRef.current
    if (uid == null || !sources.length) return
    setItems((prev) => prev.map((it) => (it.uid === uid ? { ...it, sources } : it)))
  }

  async function streamAnswer(message: string): Promise<boolean> {
    let res: Response
    try {
      res = await api.openChatStream(
        { message, mode: 'auto', conversation_id: convIdRef.current },
        abortRef.current?.signal,
      )
    } catch {
      return false
    }
    if (!res.ok) {
      if (res.status === 429) {
        const data = await res.json().catch(() => ({}))
        setTyping(false)
        appendMessage('assistant', `⚠️ ${(data as { detail?: string }).detail || 'Too many requests — please wait a moment.'}`)
        return true
      }
      return false
    }
    if (!res.body) return false

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let started = false
    let mode: string | null = null

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          let evt: {
            type: string
            mode?: string
            conversation_id?: number
            text?: string
            message?: string
            sources?: string[]
          }
          try {
            evt = JSON.parse(line.slice(5).trim())
          } catch {
            continue
          }
          if (evt.type === 'meta') {
            mode = evt.mode ?? null
            if (evt.conversation_id) setConv(evt.conversation_id)
            setTyping(false)
            startAssistantBubble(mode)
            started = true
          } else if (evt.type === 'status') {
            // Transient status from the web-search agent (e.g. "Searching the
            // web…", "Refining the search…") — shown in place of the answer
            // until the first real chunk arrives, which overwrites it since
            // updateAssistantContent() replaces the whole bubble content
            // rather than appending (rawRef.current, the real answer
            // accumulator, is untouched here).
            if (!started) {
              setTyping(false)
              startAssistantBubble(mode)
              started = true
            }
            updateAssistantContent(evt.text || '')
          } else if (evt.type === 'chunk') {
            if (!started) {
              setTyping(false)
              startAssistantBubble(mode)
              started = true
            }
            rawRef.current += evt.text || ''
            updateAssistantContent(rawRef.current)
            scrollChat()
          } else if (evt.type === 'done') {
            if (evt.sources && evt.sources.length) setAssistantSources(evt.sources)
          } else if (evt.type === 'error') {
            if (!started) return false
            rawRef.current += (rawRef.current ? '\n\n' : '') + 'Error: ' + (evt.message || 'something went wrong')
            updateAssistantContent(rawRef.current)
          }
        }
      }
    } catch {
      if (!started) return false
    }
    if (!started) return false
    return true
  }

  async function nonStreamAnswer(message: string) {
    try {
      const res = await api.sendChat({ message, mode: 'auto', conversation_id: convIdRef.current })
      const data = await res.json()
      setTyping(false)
      if (res.ok) appendMessage('assistant', data.response, data.mode, data.sources || null)
      else appendMessage('assistant', `Error: ${data.detail || 'Something went wrong.'}`)
    } catch {
      setTyping(false)
      appendMessage('assistant', 'Connection error. Please check the server.')
    }
  }

  async function getAnswer(message: string) {
    setIsLoading(true)
    isLoadingRef.current = true
    abortedRef.current = false
    abortRef.current = new AbortController()
    setTyping(true)

    let handled = false
    try {
      handled = await streamAnswer(message)
    } catch {
      handled = false
    }
    if (!handled && !abortedRef.current) {
      await nonStreamAnswer(message)
    } else if (!handled && abortedRef.current) {
      setTyping(false)
    }

    setIsLoading(false)
    isLoadingRef.current = false
    abortRef.current = null
    refreshConversationList()
  }

  async function sendMessage() {
    if (isLoadingRef.current) {
      stopGenerating()
      return
    }
    if (uploadInProgressRef.current) {
      showToast('Please wait — file is still uploading', 'warning')
      return
    }
    const message = input.trim()
    if (!message) return
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    hasMessagesRef.current = true
    saveConvSession(convIdRef.current)
    appendMessage('user', message)
    lastUserMessageRef.current = message
    await getAnswer(message)
  }

  function regenerate() {
    if (isLoadingRef.current || !lastUserMessageRef.current) return
    // Drop the last assistant message, then re-ask the last user message.
    setItems((prev) => {
      const idx = [...prev].reverse().findIndex((it) => it.role === 'assistant')
      if (idx === -1) return prev
      const realIdx = prev.length - 1 - idx
      return prev.filter((_, i) => i !== realIdx)
    })
    getAnswer(lastUserMessageRef.current)
  }

  function editUserMessage(uid: number, rawText: string) {
    if (isLoadingRef.current) stopGenerating()
    setItems((prev) => {
      const idx = prev.findIndex((it) => it.uid === uid)
      if (idx === -1) return prev
      return prev.slice(0, idx)
    })
    setInput(rawText)
    requestAnimationFrame(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        ta.style.height = 'auto'
        ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
      }
    })
  }

  // ── File uploads (unified: scope to this chat only, or all chats forever) ──
  // uploadScopeRef holds the choice made in the attach-menu popover so
  // handleFileSelect (fired by the native file dialog's onChange) knows how
  // to scope the upload without threading it through more state.
  const uploadScopeRef = useRef<'this' | 'all'>('this')

  function triggerFileInput() {
    if (!convIdRef.current) {
      showToast('Start a conversation first', 'warning')
      return
    }
    setShowAttachMenu((v) => !v)
  }

  function pickScopeAndUpload(scope: 'this' | 'all') {
    uploadScopeRef.current = scope
    setShowAttachMenu(false)
    fileInputRef.current?.click()
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    e.target.value = ''
    const scope = uploadScopeRef.current
    const conversationId = scope === 'this' ? (convIdRef.current as number) : null
    uploadInProgressRef.current = true
    for (const file of files) {
      try {
        const res = await api.uploadDocument(file, conversationId)
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          showToast(`${file.name}: ${(data as { detail?: string }).detail || 'Upload failed'}`, 'error')
          if (res.status === 400) break
          continue
        }
        const data = await res.json()
        if (conversationId) hasDocumentRef.current = true
        addSystemNote(
          conversationId
            ? `📎 ${data.filename} uploaded — available in this conversation only, while it exists.`
            : `📎 ${data.filename} uploaded — available in every conversation, from now on.`,
        )
      } catch {
        showToast(`${file.name}: upload failed`, 'error')
      }
    }
    uploadInProgressRef.current = false
  }

  // ── Input handlers ───────────────────────────────────────────────────────────
  function onInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  }
  function onInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }
  function useHint(text: string) {
    setInput(text)
    textareaRef.current?.focus()
  }

  const realMessages = items.filter((it) => it.role === 'user' || it.role === 'assistant')
  const lastAssistantUid = [...items].reverse().find((it) => it.role === 'assistant')?.uid ?? null

  return (
    <ArtifactProvider>
      <div className={`sidebar-overlay${sidebarOpen ? ' open' : ''}`} onClick={closeSidebar} />
      <div className={`app-layout${collapsed ? ' sidebar-collapsed' : ''}`}>
        {/* Sidebar */}
        <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
          <div className="sidebar-top-bar">
            <button className="new-chat-btn" onClick={newConversation}>
              <span className="icon">➕</span> New Chat
            </button>
            <button className="sidebar-collapse-btn" onClick={toggleDesktopSidebar} title="Collapse sidebar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M9 3v18" />
                <path d="M15 9l-3 3 3 3" />
              </svg>
            </button>
          </div>

          <div className="sidebar-tabs">
            <div
              className={`sidebar-tab${sidebarTab === 'chats' ? ' active' : ''}`}
              onClick={() => setSidebarTab('chats')}
            >
              Chats
            </div>
            <div
              className={`sidebar-tab${sidebarTab === 'documents' ? ' active' : ''}`}
              onClick={() => setSidebarTab('documents')}
            >
              Documents
            </div>
          </div>

          {sidebarTab === 'documents' ? (
            <DocumentPanel
              currentConversationId={currentConversationId}
              onChatScopedUpload={() => { hasDocumentRef.current = true }}
            />
          ) : (
          <div className="conv-list">
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`conv-item${c.id === currentConversationId ? ' active' : ''}`}
                onClick={() => switchConversation(c.id)}
              >
                {editingId === c.id ? (
                  <input
                    className="conv-rename-input"
                    autoFocus
                    value={editingValue}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => setEditingValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        const val = editingValue.trim()
                        setEditingId(null)
                        if (val && val !== c.title) commitRename(c.id, val)
                      } else if (e.key === 'Escape') {
                        setEditingId(null)
                      }
                    }}
                    onBlur={() => {
                      const val = editingValue.trim()
                      setEditingId(null)
                      if (val && val !== c.title) commitRename(c.id, val)
                    }}
                  />
                ) : (
                  <span
                    className="conv-title"
                    title="Double-click to rename"
                    onDoubleClick={(e) => {
                      e.stopPropagation()
                      setEditingId(c.id)
                      setEditingValue(c.title || 'New chat')
                    }}
                  >
                    {c.title || 'New chat'}
                  </span>
                )}
                <button
                  className="conv-del"
                  title="Delete conversation"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteConversation(c.id)
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
          )}

          <div className="sidebar-bottom">
            <div className="user-info">
              <div className="user-avatar">{username ? username[0].toUpperCase() : '?'}</div>
              <div>
                <div className="user-name">{username}</div>
              </div>
            </div>
            <button
              className="btn btn-secondary btn-sm"
              style={{ width: '100%', justifyContent: 'center' }}
              onClick={logout}
            >
              Sign Out
            </button>
          </div>
        </aside>

        {/* Main */}
        <main style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div className="chat-header">
            <div className="chat-header-left">
              <button className="mobile-menu-btn" onClick={() => setSidebarOpen((v) => !v)} title="Menu">
                ☰
              </button>
              {collapsed && (
                <button
                  className="expand-sidebar-btn"
                  style={{ display: 'flex' }}
                  onClick={toggleDesktopSidebar}
                  title="Show sidebar"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                    <path d="M9 3v18" />
                    <path d="M15 15l3-3-3-3" />
                  </svg>
                </button>
              )}
              <h2>kGPT</h2>
            </div>
            <div className="chat-header-actions">
              <button className="theme-toggle-btn-header" onClick={toggleTheme} title="Toggle Theme">
                <span className="theme-icon">{light ? '☀️' : '🌙'}</span>
              </button>
            </div>
          </div>

          <div className="chat-messages-container" ref={scrollRef}>
            <div className="chat-messages">
              {items.map((it) =>
                it.role === 'system' ? (
                  <div className="system-note" key={it.uid}>
                    {it.content}
                  </div>
                ) : (
                  <MessageItem
                    key={it.uid}
                    item={it}
                    isLast={it.uid === lastAssistantUid}
                    isLoading={isLoading}
                    canRegenerate={!!lastUserMessageRef.current}
                    onEdit={editUserMessage}
                    onRegenerate={regenerate}
                  />
                ),
              )}

              {typing && (
                <div className="message assistant">
                  <div className="message-avatar">🧠</div>
                  <div className="message-content">
                    <div className="typing-indicator">
                      <div className="typing-dot" />
                      <div className="typing-dot" />
                      <div className="typing-dot" />
                    </div>
                  </div>
                </div>
              )}

              {realMessages.length === 0 && (
                <div className="empty-state">
                  <div className="big-icon">🧠</div>
                  <h3>Welcome to kGPT</h3>
                  <p>One clean input box. kGPT automatically decides whether to answer directly or search the web.</p>
                  <div className="suggestions-grid">
                    <div className="suggestion-card" onClick={() => useHint('Search for the latest AI news')}>
                      <div className="suggestion-icon">🌐</div>
                      <div className="suggestion-title">Web Search</div>
                      <div className="suggestion-text">"Search for the latest AI news"</div>
                    </div>
                    <div className="suggestion-card" onClick={() => useHint('Explain how neural networks work')}>
                      <div className="suggestion-icon">🧠</div>
                      <div className="suggestion-title">General Chat</div>
                      <div className="suggestion-text">"Explain how neural networks work"</div>
                    </div>
                    <div className="suggestion-card" onClick={triggerFileInput}>
                      <div className="suggestion-icon">📎</div>
                      <div className="suggestion-title">Documents</div>
                      <div className="suggestion-text">Attach PDF, DOCX, or images</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="chat-input-area">
            <div className="input-container-centered">
              <div className="input-row">
                <div className="attach-menu-wrap">
                  <button
                    className="attach-btn"
                    onClick={triggerFileInput}
                    title="Attach file (jpg, png, pdf, docx, txt, md)"
                  />
                  {showAttachMenu && (
                    <div className="attach-menu">
                      <div className="attach-menu-item" onClick={() => pickScopeAndUpload('this')}>
                        This chat only
                        <small>Available only while this conversation exists</small>
                      </div>
                      <div className="attach-menu-item" onClick={() => pickScopeAndUpload('all')}>
                        All chats
                        <small>Available in every conversation, from now on</small>
                      </div>
                    </div>
                  )}
                </div>
                <div className="input-wrapper">
                  <textarea
                    ref={textareaRef}
                    rows={1}
                    placeholder="Ask kGPT anything..."
                    value={input}
                    onChange={onInputChange}
                    onKeyDown={onInputKeyDown}
                  />
                </div>
                <button
                  className={`send-btn${isLoading ? ' generating' : ''}`}
                  onClick={sendMessage}
                  title={isLoading ? 'Stop generating' : 'Send'}
                >
                  {isLoading ? '⏹' : '➤'}
                </button>
              </div>
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.pdf,.docx,.txt,.md"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileSelect}
          />
        </main>
      </div>
    </ArtifactProvider>
  )
}

// ── Message item ───────────────────────────────────────────────────────────────
function MessageItem({
  item,
  isLast,
  isLoading,
  canRegenerate,
  onEdit,
  onRegenerate,
}: {
  item: Item
  isLast: boolean
  isLoading: boolean
  canRegenerate: boolean
  onEdit: (uid: number, text: string) => void
  onRegenerate: () => void
}) {
  const [time] = useState(nowTime)
  const isUser = item.role === 'user'
  const showBadge = item.role === 'assistant' && item.mode === 'web'
  const sourceCount = item.sources?.length || 0

  return (
    <div className={`message ${item.role}`}>
      <div className="message-avatar">{isUser ? '👤' : '🧠'}</div>
      <div className="message-body">
        <div className="message-content">
          {showBadge && (
            <div className="tool-badge">
              <span>🌐</span> Web Search
            </div>
          )}
          {sourceCount > 0 && (
            <div className="tool-badge" title={item.sources?.join(', ')}>
              <span>📚</span> Used {sourceCount} source{sourceCount === 1 ? '' : 's'}
            </div>
          )}
          {isUser ? (
            <div className="md" style={{ whiteSpace: 'pre-wrap' }}>
              {item.content}
            </div>
          ) : (
            <Markdown text={item.content} />
          )}
        </div>

        <div className="message-actions">
          <button
            className="msg-action-btn"
            type="button"
            onClick={() => {
              copyToClipboard(item.content)
              showToast('Copied to clipboard', 'success')
            }}
          >
            📋 Copy
          </button>
          {isUser && (
            <button className="msg-action-btn" type="button" onClick={() => onEdit(item.uid, item.content)}>
              ✏️ Edit
            </button>
          )}
          {!isUser && isLast && !isLoading && canRegenerate && (
            <button className="msg-action-btn regenerate-btn" type="button" onClick={onRegenerate}>
              🔄 Regenerate
            </button>
          )}
        </div>

        <div className="message-time">{time}</div>
      </div>
    </div>
  )
}
