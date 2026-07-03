import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { apiVerifyEmail, extractError } from '../api/client'

type Phase = 'loading' | 'ok' | 'error' | 'notoken'

export default function Verify() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { saveToken } = useAuth()
  const [phase, setPhase] = useState<Phase>('loading')
  const [subtitle, setSubtitle] = useState('Verifying your email address…')
  const [status, setStatus] = useState('')
  const ran = useRef(false)

  useEffect(() => {
    document.body.classList.add('auth-scroll')
    return () => document.body.classList.remove('auth-scroll')
  }, [])

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    const token = params.get('token')
    if (!token) {
      setPhase('notoken')
      setSubtitle('Invalid verification link.')
      setStatus('No token found in the URL. Please use the link from your email.')
      return
    }
    ;(async () => {
      try {
        const res = await apiVerifyEmail(token)
        const data = await res.json()
        if (res.ok) {
          saveToken(data.access_token)
          setPhase('ok')
          setSubtitle('Email verified!')
          setStatus('Your account is now active. Redirecting…')
          setTimeout(() => navigate('/'), 2500)
        } else {
          setPhase('error')
          setSubtitle('Verification failed.')
          setStatus(extractError(data, 'Invalid or expired verification link.'))
        }
      } catch {
        setPhase('error')
        setSubtitle('Connection error.')
        setStatus('Could not reach the server. Make sure the app is running.')
      }
    })()
  }, [params, saveToken, navigate])

  const icon = phase === 'loading' ? '🔑' : phase === 'ok' ? '✅' : '❌'

  return (
    <div className="verify-card">
      <div className="verify-icon">{icon}</div>
      <h1>
        <span>k</span>GPT
      </h1>
      <p>{subtitle}</p>
      {phase === 'loading' && <div className="spinner" />}
      <div className={`verify-status${phase === 'ok' ? ' ok' : phase === 'error' || phase === 'notoken' ? ' error' : ''}`}>
        {status}
      </div>
      {phase === 'ok' && (
        <Link className="go-btn" to="/">
          Open kGPT →
        </Link>
      )}
      {phase === 'error' && (
        <p className="redirect-msg">
          <Link to="/login">Back to login</Link> to request a new link.
        </p>
      )}
    </div>
  )
}
