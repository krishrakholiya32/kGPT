import { createContext, useContext, useState, type ReactNode } from 'react'
import { getToken, setToken as persistToken, clearToken } from '../api/client'

interface AuthContextValue {
  token: string | null
  saveToken: (t: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState<string | null>(getToken())

  const saveToken = (t: string) => {
    persistToken(t)
    setTok(t)
  }

  const logout = () => {
    clearToken()
    // Clearing the active-conversation session key ensures the next login always
    // starts fresh — matches the original chat.js logout behaviour.
    sessionStorage.removeItem('kgpt_conv')
    setTok(null)
  }

  return <AuthContext.Provider value={{ token, saveToken, logout }}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
