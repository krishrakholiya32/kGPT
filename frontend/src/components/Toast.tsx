import { useEffect, useState } from 'react'

// Lightweight global toast, mirroring the original showToast() helper.

export type ToastType = 'success' | 'error' | 'warning'
interface ToastItem {
  id: number
  message: string
  type: ToastType
}

let _id = 0
const listeners = new Set<(items: ToastItem[]) => void>()
let items: ToastItem[] = []

function emit() {
  for (const l of listeners) l(items)
}

export function showToast(message: string, type: ToastType = 'success') {
  const item: ToastItem = { id: ++_id, message, type }
  items = [...items, item]
  emit()
  setTimeout(() => {
    items = items.filter((i) => i.id !== item.id)
    emit()
  }, 3000)
}

const ICONS: Record<ToastType, string> = { success: '✅', error: '❌', warning: '⚠️' }

export function ToastContainer() {
  const [list, setList] = useState<ToastItem[]>(items)
  useEffect(() => {
    listeners.add(setList)
    return () => {
      listeners.delete(setList)
    }
  }, [])
  return (
    <div className="toast-container">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.type}`}>
          <span>{ICONS[t.type]}</span>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}
