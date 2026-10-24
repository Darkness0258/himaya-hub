import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Tone } from './describe'

interface ToastItem {
  id: number
  text: string
  tone: Tone
}

interface ToastApi {
  push: (text: string, tone?: Tone) => void
}

const ToastContext = createContext<ToastApi>({ push: () => undefined })

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const push = useCallback((text: string, tone: Tone = 'neutral') => {
    const id = nextId.current++
    setItems((current) => [...current.slice(-3), { id, text, tone }])
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), tone === 'bad' ? 7000 : 4000)
  }, [])

  const api = useMemo(() => ({ push }), [push])
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast toast--${item.tone}`}>
            {item.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  return useContext(ToastContext)
}
