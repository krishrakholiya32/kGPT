import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { apiLogin, apiRegister, apiCheck, extractError } from '../api/client'

type Tab = 'login' | 'register'
interface Hint {
  state: '' | 'ok' | 'error' | 'loading'
  msg: string
}
const EMPTY_HINT: Hint = { state: '', msg: '' }

const USERNAME_RE = /^[A-Za-z0-9_]{3,30}$/
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function Login() {
  const navigate = useNavigate()
  const { token, saveToken } = useAuth()

  const [tab, setTab] = useState<Tab>('login')
  const [error, setError] = useState('')

  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')

  const [regUsername, setRegUsername] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regEmailConfirm, setRegEmailConfirm] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regPasswordConfirm, setRegPasswordConfirm] = useState('')

  const [hintUsername, setHintUsername] = useState<Hint>(EMPTY_HINT)
  const [hintEmail, setHintEmail] = useState<Hint>(EMPTY_HINT)
  const [hintEmailConfirm, setHintEmailConfirm] = useState<Hint>(EMPTY_HINT)
  const [hintPasswordConfirm, setHintPasswordConfirm] = useState<Hint>(EMPTY_HINT)

  // "readonly until focus" trick to block iOS autofill/privacy keyboard.
  const [activated, setActivated] = useState<Record<string, boolean>>({})
  const activate = (k: string) => setActivated((a) => (a[k] ? a : { ...a, [k]: true }))
  const ro = (k: string) => !activated[k]

  const usernameTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const emailTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Redirect if already logged in (checked once on mount).
  const bootToken = useRef(token)
  useEffect(() => {
    if (bootToken.current) navigate('/', { replace: true })
  }, [navigate])

  useEffect(() => {
    document.body.classList.add('auth-scroll')
    return () => document.body.classList.remove('auth-scroll')
  }, [])

  function switchTab(t: Tab) {
    setTab(t)
    setError('')
  }

  async function doLogin() {
    const email = loginEmail.trim()
    if (!email || !loginPassword) {
      setError('Please fill in all fields.')
      return
    }
    try {
      const res = await apiLogin(email, loginPassword)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(extractError(data, 'Login failed.'))
        return
      }
      saveToken(data.access_token)
      navigate('/')
    } catch {
      setError('Connection error. Make sure the server is running.')
    }
  }

  async function doRegister() {
    const username = regUsername.trim()
    const email = regEmail.trim()
    const emailConfirm = regEmailConfirm.trim()
    if (!username || !email || !emailConfirm || !regPassword || !regPasswordConfirm) {
      setError('Please fill in all fields.')
      return
    }
    if (email !== emailConfirm) {
      setError('Email addresses do not match.')
      return
    }
    if (regPassword !== regPasswordConfirm) {
      setError('Passwords do not match.')
      return
    }
    try {
      const res = await apiRegister(username, email, regPassword)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(extractError(data, 'Registration failed.'))
        return
      }
      saveToken(data.access_token)
      navigate('/')
    } catch {
      setError('Connection error. Make sure the server is running.')
    }
  }

  function onUsernameChange(val: string) {
    setRegUsername(val)
    if (usernameTimer.current) clearTimeout(usernameTimer.current)
    usernameTimer.current = setTimeout(async () => {
      const v = val.trim()
      if (!v) return setHintUsername(EMPTY_HINT)
      if (!USERNAME_RE.test(v)) {
        return setHintUsername({ state: 'error', msg: '3–30 characters, letters/numbers/underscores only' })
      }
      setHintUsername({ state: 'loading', msg: 'Checking…' })
      try {
        const d = await apiCheck({ username: v })
        setHintUsername(
          d.username?.taken
            ? { state: 'error', msg: 'Username already taken' }
            : { state: 'ok', msg: 'Username available ✓' },
        )
      } catch {
        setHintUsername(EMPTY_HINT)
      }
    }, 500)
  }

  function onEmailChange(val: string) {
    setRegEmail(val)
    if (emailTimer.current) clearTimeout(emailTimer.current)
    emailTimer.current = setTimeout(async () => {
      const v = val.trim()
      if (!v) return setHintEmail(EMPTY_HINT)
      if (!EMAIL_RE.test(v)) {
        return setHintEmail({ state: 'error', msg: 'Enter a valid email address' })
      }
      setHintEmail({ state: 'loading', msg: 'Checking…' })
      try {
        const d = await apiCheck({ email: v })
        setHintEmail(
          d.email?.taken
            ? { state: 'error', msg: 'Email already registered' }
            : { state: 'ok', msg: 'Email available ✓' },
        )
      } catch {
        setHintEmail(EMPTY_HINT)
      }
    }, 500)
  }

  function onEmailConfirmChange(val: string) {
    setRegEmailConfirm(val)
    const v = val.trim()
    if (!v) return setHintEmailConfirm(EMPTY_HINT)
    setHintEmailConfirm(
      v === regEmail.trim()
        ? { state: 'ok', msg: 'Emails match ✓' }
        : { state: 'error', msg: 'Emails do not match' },
    )
  }

  function onPasswordConfirmChange(val: string) {
    setRegPasswordConfirm(val)
    if (!val) return setHintPasswordConfirm(EMPTY_HINT)
    setHintPasswordConfirm(
      val === regPassword
        ? { state: 'ok', msg: 'Passwords match ✓' }
        : { state: 'error', msg: 'Passwords do not match' },
    )
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== 'Enter') return
    if (tab === 'login') doLogin()
    else doRegister()
  }

  return (
    <div className="auth-page" onKeyDown={onKeyDown}>
      <div className="auth-card">
        <div className="auth-logo">
          <h1>kGPT</h1>
          <p>Your Private AI Assistant</p>
        </div>

        <div className="auth-tabs">
              <div className={`auth-tab${tab === 'login' ? ' active' : ''}`} onClick={() => switchTab('login')}>
                Login
              </div>
              <div className={`auth-tab${tab === 'register' ? ' active' : ''}`} onClick={() => switchTab('register')}>
                Register
              </div>
            </div>

            <div className={`auth-error${error ? ' show' : ''}`}>{error}</div>

            {tab === 'login' && (
              <div>
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="text"
                    inputMode="email"
                    placeholder="Enter your email"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    readOnly={ro('loginEmail')}
                    onFocus={() => activate('loginEmail')}
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Password</label>
                  <input
                    type="password"
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                  />
                </div>
                <button
                  className="btn btn-primary"
                  style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}
                  onClick={doLogin}
                >
                  Sign In →
                </button>
              </div>
            )}

            {tab === 'register' && (
              <div className="form-register">
                <div className="form-group">
                  <label>Username</label>
                  <input
                    type="text"
                    placeholder="Choose a username"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    readOnly={ro('regUsername')}
                    onFocus={() => activate('regUsername')}
                    value={regUsername}
                    onChange={(e) => onUsernameChange(e.target.value)}
                  />
                  <span className={`field-hint ${hintUsername.state}`}>{hintUsername.msg}</span>
                </div>
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="text"
                    inputMode="email"
                    placeholder="Your email address"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    readOnly={ro('regEmail')}
                    onFocus={() => activate('regEmail')}
                    value={regEmail}
                    onChange={(e) => onEmailChange(e.target.value)}
                  />
                  <span className={`field-hint ${hintEmail.state}`}>{hintEmail.msg}</span>
                </div>
                <div className="form-group">
                  <label>Confirm Email</label>
                  <input
                    type="text"
                    inputMode="email"
                    placeholder="Re-enter your email"
                    autoComplete="off"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    readOnly={ro('regEmailConfirm')}
                    onFocus={() => activate('regEmailConfirm')}
                    value={regEmailConfirm}
                    onChange={(e) => onEmailConfirmChange(e.target.value)}
                  />
                  <span className={`field-hint ${hintEmailConfirm.state}`}>{hintEmailConfirm.msg}</span>
                </div>
                <div className="form-group">
                  <label>Password</label>
                  <input
                    type="password"
                    placeholder="Choose a password"
                    autoComplete="new-password"
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                  />
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                    At least 8 characters, including an uppercase letter, a lowercase letter, a number, and a special
                    character.
                  </p>
                </div>
                <div className="form-group">
                  <label>Confirm Password</label>
                  <input
                    type="password"
                    placeholder="Re-enter your password"
                    autoComplete="new-password"
                    value={regPasswordConfirm}
                    onChange={(e) => onPasswordConfirmChange(e.target.value)}
                  />
                  <span className={`field-hint ${hintPasswordConfirm.state}`}>{hintPasswordConfirm.msg}</span>
                </div>
                <button
                  className="btn btn-primary"
                  style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}
                  onClick={doRegister}
                >
                  Create Account →
                </button>
              </div>
            )}
      </div>
    </div>
  )
}
