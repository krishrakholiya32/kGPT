// Fetch-based API client for kGPT.
//
// Uses same-origin paths by default (VITE_API_URL empty). In dev the Vite proxy
// forwards /api to the FastAPI backend; in production FastAPI serves this SPA on
// the same origin. Streaming uses raw fetch + a ReadableStream reader so the SSE
// parsing behaviour matches the original vanilla-JS app exactly.

export const API: string = import.meta.env.VITE_API_URL || ''

const TOKEN_KEY = 'kgpt_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' }
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface Conversation {
  id: number
  title: string
  updated_at: string | null
  attachment_name: string | null
  message_count: number
  attachment_names: string[]
}

export interface Message {
  id: number
  role: string
  content: string
  mode: string | null
  timestamp: string | null
}

export interface CurrentUser {
  id: number
  username: string
  email: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  email_verified: boolean
}

// ── Error extraction (mirrors the original extractError) ─────────────────────

export function extractError(data: unknown, fallback: string): string {
  const d = data && (data as { detail?: unknown }).detail
  if (!d) return fallback
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    const msgs = d
      .map((e) => (e && (e as { msg?: string }).msg ? (e as { msg: string }).msg.replace(/^Value error,\s*/i, '') : ''))
      .filter(Boolean)
    return msgs.length ? msgs.join(' ') : fallback
  }
  return fallback
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function apiLogin(email: string, password: string): Promise<Response> {
  const form = new URLSearchParams()
  form.append('username', email) // OAuth2 form field is always 'username'
  form.append('password', password)
  return fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })
}

export async function apiRegister(username: string, email: string, password: string): Promise<Response> {
  return fetch(`${API}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
}

export async function apiVerifyEmail(token: string): Promise<Response> {
  return fetch(`${API}/api/auth/verify-email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
}

export async function apiResendVerification(email: string): Promise<Response> {
  return fetch(`${API}/api/auth/resend-verification`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
}

export interface CheckResult {
  username?: { valid_format: boolean; taken: boolean }
  email?: { valid_format: boolean; taken: boolean }
}

export async function apiCheck(params: { username?: string; email?: string }): Promise<CheckResult> {
  const qs = new URLSearchParams()
  if (params.username !== undefined) qs.set('username', params.username)
  if (params.email !== undefined) qs.set('email', params.email)
  const r = await fetch(`${API}/api/auth/check?${qs.toString()}`)
  return r.json()
}

export async function apiMe(): Promise<Response> {
  return fetch(`${API}/api/auth/me`, { headers: authHeaders() })
}

// ── Conversations ────────────────────────────────────────────────────────────

export async function listConversations(): Promise<Conversation[]> {
  const res = await fetch(`${API}/api/chat/conversations`, { headers: authHeaders() })
  if (!res.ok) throw new Error('failed to list conversations')
  return res.json()
}

export async function createConversation(): Promise<Conversation | null> {
  try {
    const res = await fetch(`${API}/api/chat/conversations`, { method: 'POST', headers: authHeaders() })
    if (res.ok) return res.json()
  } catch {
    /* ignore */
  }
  return null
}

export async function getMessages(id: number): Promise<Message[]> {
  const res = await fetch(`${API}/api/chat/conversations/${id}/messages`, { headers: authHeaders() })
  if (!res.ok) throw new Error('failed to load messages')
  return res.json()
}

export async function deleteConversationSilent(id: number): Promise<void> {
  try {
    await fetch(`${API}/api/chat/conversations/${id}`, { method: 'DELETE', headers: authHeaders() })
  } catch {
    /* ignore */
  }
}

export async function deleteConversation(id: number): Promise<boolean> {
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}`, { method: 'DELETE', headers: authHeaders() })
    return res.ok
  } catch {
    return false
  }
}

export async function renameConversation(id: number, title: string): Promise<boolean> {
  try {
    const res = await fetch(`${API}/api/chat/conversations/${id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ title }),
    })
    return res.ok
  } catch {
    return false
  }
}

export async function uploadAttachment(convId: number, file: File): Promise<Response> {
  const formData = new FormData()
  formData.append('file', file)
  return fetch(`${API}/api/chat/conversations/${convId}/attachment`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: formData,
  })
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatBody {
  message: string
  mode: string
  conversation_id: number | null
}

export async function openChatStream(body: ChatBody, signal?: AbortSignal): Promise<Response> {
  return fetch(`${API}/api/chat/stream`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
    signal,
  })
}

export async function sendChat(body: ChatBody): Promise<Response> {
  return fetch(`${API}/api/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
}
