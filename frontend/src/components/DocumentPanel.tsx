import { useEffect, useRef, useState } from 'react'
import { listDocuments, uploadDocument, deleteDocument, type KnowledgeDoc } from '../api/client'
import { showToast } from './Toast'

const STATUS_LABEL: Record<string, string> = {
  processing: 'Processing…',
  ready: 'Ready',
  failed: 'Failed',
}

export default function DocumentPanel() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([])
  const [loading, setLoading] = useState(true)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  async function refresh() {
    try {
      const list = await listDocuments()
      setDocs(list)
    } catch {
      /* leave existing list on transient failure */
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current)
    }
  }, [])

  // Poll while any document is still processing.
  useEffect(() => {
    const anyProcessing = docs.some((d) => d.status === 'processing')
    if (anyProcessing && !pollTimer.current) {
      pollTimer.current = setInterval(refresh, 2000)
    } else if (!anyProcessing && pollTimer.current) {
      clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }, [docs])

  function triggerUpload() {
    fileInputRef.current?.click()
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return
    for (const file of Array.from(files)) {
      try {
        const res = await uploadDocument(file)
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          showToast(data.detail || `Failed to upload ${file.name}`, 'error')
          continue
        }
        showToast(`${file.name} uploaded — processing…`, 'success')
        refresh()
      } catch {
        showToast(`Failed to upload ${file.name}`, 'error')
      }
    }
    e.target.value = ''
  }

  async function handleDelete(id: number, filename: string) {
    const ok = await deleteDocument(id)
    if (ok) {
      showToast(`${filename} removed`, 'success')
      setDocs((prev) => prev.filter((d) => d.id !== id))
    } else {
      showToast(`Failed to remove ${filename}`, 'error')
    }
  }

  return (
    <div className="conv-list doc-list">
      <input
        ref={fileInputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.pdf,.docx,.txt,.md"
        multiple
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />
      <button className="new-chat-btn" onClick={triggerUpload} title="Upload a document (jpg, png, pdf, docx, txt, md)">
        <span className="icon">📄</span> Upload document
      </button>

      {loading && <div className="doc-empty-hint">Loading…</div>}
      {!loading && docs.length === 0 && (
        <div className="doc-empty-hint">
          No documents yet. Upload one to let kGPT answer questions using its content, in any chat.
        </div>
      )}

      {docs.map((d) => (
        <div key={d.id} className="conv-item doc-item">
          <span className="conv-title" title={d.error_message || undefined}>
            {d.filename}
            <span className={`doc-status doc-status-${d.status}`}>
              {' '}
              {STATUS_LABEL[d.status] || d.status}
              {d.status === 'ready' && d.chunk_count ? ` · ${d.chunk_count} chunk${d.chunk_count === 1 ? '' : 's'}` : ''}
            </span>
          </span>
          <button className="conv-del" title="Delete document" onClick={() => handleDelete(d.id, d.filename)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}
