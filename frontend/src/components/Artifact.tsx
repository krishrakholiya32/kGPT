import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

// Artifacts-style live preview for HTML/SVG code blocks, in a sandboxed iframe.
// Mirrors the original ensureArtifactPanel/openArtifact logic.

interface ArtifactContextValue {
  openArtifact: (code: string) => void
}

const ArtifactContext = createContext<ArtifactContextValue | undefined>(undefined)

// eslint-disable-next-line react-refresh/only-export-components
export function useArtifact() {
  const ctx = useContext(ArtifactContext)
  if (!ctx) throw new Error('useArtifact must be used within ArtifactProvider')
  return ctx
}

function buildSrcDoc(codeText: string): string {
  const t = codeText.trim().toLowerCase()
  if (t.startsWith('<svg')) {
    return (
      '<!DOCTYPE html><html><head><meta charset="utf-8">' +
      '<style>body{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#fff}</style>' +
      '</head><body>' +
      codeText +
      '</body></html>'
    )
  }
  return codeText
}

export function ArtifactProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [tab, setTab] = useState<'preview' | 'code'>('preview')

  const openArtifact = useCallback((c: string) => {
    setCode(c)
    setTab('preview')
    setOpen(true)
  }, [])

  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [close])

  return (
    <ArtifactContext.Provider value={{ openArtifact }}>
      {children}
      <div className={`artifact-overlay${open ? ' open' : ''}`} onClick={close} />
      <div className={`artifact-panel${open ? ' open' : ''}`}>
        <div className="artifact-header">
          <span className="artifact-title">Preview</span>
          <div className="artifact-tabs">
            <button
              type="button"
              className={`artifact-tab${tab === 'preview' ? ' active' : ''}`}
              onClick={() => setTab('preview')}
            >
              Preview
            </button>
            <button
              type="button"
              className={`artifact-tab${tab === 'code' ? ' active' : ''}`}
              onClick={() => setTab('code')}
            >
              Code
            </button>
          </div>
          <button type="button" className="artifact-close" onClick={close}>
            ✕
          </button>
        </div>
        <div className="artifact-body">
          <iframe
            className="artifact-frame"
            title="artifact-preview"
            sandbox="allow-scripts allow-modals"
            srcDoc={open ? buildSrcDoc(code) : ''}
            style={{ display: tab === 'code' ? 'none' : 'block' }}
          />
          <pre className="artifact-code" style={{ display: tab === 'code' ? 'block' : 'none' }}>
            {code}
          </pre>
        </div>
      </div>
    </ArtifactContext.Provider>
  )
}
