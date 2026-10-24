import { ChevronLeft, ChevronRight, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { dateTime, timeAgo } from '../lib/format'
import type { Snapshot } from '../lib/types'
import { Button, ConfirmDialog } from './ui'

export function ScreenGrid({ items, deviceName, hasMore, onLoadMore, onDelete, onImageError, now }: { items: Snapshot[]; deviceName: (id: string) => string; hasMore: boolean; onLoadMore: () => Promise<void>; onDelete: (id: number) => Promise<void>; onImageError: () => void; now: number }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const lastError = useRef(0)

  const current = openIndex !== null ? items[openIndex] : undefined
  const close = useCallback(() => setOpenIndex(null), [])
  const step = useCallback(
    (delta: number) => setOpenIndex((index) => (index === null ? null : Math.min(items.length - 1, Math.max(0, index + delta)))),
    [items.length],
  )

  useEffect(() => {
    if (openIndex === null || confirming) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') step(1)
      if (event.key === 'ArrowRight') step(-1)
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openIndex, confirming, step, close])

  // Signed links last 15 minutes. If one fails, ask for fresh ones (at most every 30 s).
  const imageFailed = () => {
    if (Date.now() - lastError.current > 30_000) {
      lastError.current = Date.now()
      onImageError()
    }
  }

  return (
    <>
      <ul className="shots">
        {items.map((item, index) => (
          <li key={item.id}>
            <button type="button" className="shot" onClick={() => setOpenIndex(index)} aria-label={`Open screenshot from ${deviceName(item.device_id)}, ${timeAgo(item.timestamp, now)}`}>
              <img src={item.url} alt="" loading="lazy" onError={imageFailed} />
              <span className="shot__cap">
                <span>{deviceName(item.device_id)}</span>
                <span>{timeAgo(item.timestamp, now)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {hasMore && (
        <div className="center">
          <Button
            busy={loadingMore}
            onClick={async () => {
              setLoadingMore(true)
              try {
                await onLoadMore()
              } finally {
                setLoadingMore(false)
              }
            }}
          >
            Show older
          </Button>
        </div>
      )}

      {current &&
        createPortal(
        <div className="lightbox" role="dialog" aria-modal="true" aria-label="Screenshot" hidden={confirming}>
          <button type="button" className="lightbox__scrim" aria-label="Close" onClick={close} />
          <figure className="lightbox__figure">
            <img src={current.url} alt={`Screenshot from ${deviceName(current.device_id)} at ${dateTime(current.timestamp)}`} onError={imageFailed} />
            <figcaption>
              <strong>{deviceName(current.device_id)}</strong>
              <span>{dateTime(current.timestamp)}</span>
            </figcaption>
          </figure>
          <div className="lightbox__bar">
            <button type="button" className="iconbtn" onClick={() => step(1)} disabled={openIndex === items.length - 1} aria-label="Older screenshot">
              <ChevronLeft size={20} aria-hidden="true" />
            </button>
            <button type="button" className="iconbtn" onClick={() => step(-1)} disabled={openIndex === 0} aria-label="Newer screenshot">
              <ChevronRight size={20} aria-hidden="true" />
            </button>
            <button type="button" className="iconbtn" onClick={() => setConfirming(true)} aria-label="Delete this screenshot">
              <Trash2 size={19} aria-hidden="true" />
            </button>
            <button type="button" className="iconbtn" onClick={close} aria-label="Close">
              <X size={20} aria-hidden="true" />
            </button>
          </div>
        </div>,
        document.body,
      )}

      <ConfirmDialog
        open={confirming}
        title="Delete this screenshot?"
        confirmLabel="Delete"
        danger
        busy={busy}
        onClose={() => setConfirming(false)}
        onConfirm={async () => {
          if (!current) return
          setBusy(true)
          try {
            await onDelete(current.id)
            setConfirming(false)
            setOpenIndex((index) => (index !== null && items.length <= 1 ? null : index !== null ? Math.min(index, items.length - 2) : null))
          } finally {
            setBusy(false)
          }
        }}
      >
        <p>It is removed from the hub for good. This cannot be undone.</p>
      </ConfirmDialog>
    </>
  )
}
