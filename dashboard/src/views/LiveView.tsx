import { Eye } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button, Dialog } from '../components/ui'
import { api } from '../lib/api'
import { useNow } from '../lib/hooks'
import { clock, frameUrl, LIVE_DEFAULT_S, secondsLeft } from '../lib/live'
import { useHub } from '../lib/store'
import type { Device } from '../lib/types'
import './live.css'

type Phase = 'starting' | 'live' | 'over'

/** Mounted only while the dialog is open, so closing it (or leaving the page) stops the live view. */
function LiveBody({ device, onClose }: { device: Device; onClose: () => void }) {
  const { applyDevice } = useHub()
  const now = useNow(500)
  const [phase, setPhase] = useState<Phase>('starting')
  const [error, setError] = useState('')
  const [endsAt, setEndsAt] = useState(0)
  const [src, setSrc] = useState('')
  const liveUrl = useRef('')
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    let cancelled = false
    api
      .action(device.device_id, 'live_view', { duration_s: LIVE_DEFAULT_S })
      .then((reply) => {
        if (cancelled || !reply.live) return
        applyDevice(reply.device)
        liveUrl.current = reply.live.url
        setEndsAt(Date.now() + reply.live.duration_s * 1000)
        setPhase('live')
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Live view could not start.')
        setPhase('over')
      })
    return () => {
      cancelled = true
      // Closing the dialog ends it on the hub (and so on the child's PC).
      void api.action(device.device_id, 'stop_live_view').catch(() => undefined)
    }
  }, [device.device_id, applyDevice])

  const left = phase === 'live' ? secondsLeft(endsAt, now) : 0
  const running = phase === 'live' && left > 0
  const over = phase === 'over' || (phase === 'live' && left === 0)

  // Fetch a fresh picture about once a second; swap it in only when it has loaded, so there is no flicker.
  useEffect(() => {
    if (!running) return
    let tick = 0
    const id = window.setInterval(() => {
      const img = new Image()
      const address = frameUrl(liveUrl.current, ++tick)
      img.onload = () => setSrc(address)
      img.src = address
    }, 1000)
    return () => window.clearInterval(id)
  }, [running])

  return (
    <div className="live">
      <div className="live__screen">
        {src ? <img className="live__frame" src={src} alt={`Live view of ${device.name}'s screen`} /> : <p className="live__wait">{over ? (error || 'Live view has ended.') : 'Waiting for the first picture...'}</p>}
      </div>
      <p className="live__status" role="status">
        {running && (
          <>
            <span className="live__dot" aria-hidden="true" /> Live, {clock(left)} left
          </>
        )}
        {phase === 'starting' && 'Starting...'}
        {over && (error ? 'Not started' : 'Ended. Nothing was saved.')}
      </p>
      <p className="hint">{device.name} shows a notice and its tray icon changes while this runs. It stops by itself and nothing is saved.</p>
      <div className="dialog__footer">
        <Button variant={over ? 'secondary' : 'primary'} onClick={onClose}>
          {over ? 'Close' : 'Stop'}
        </Button>
      </div>
    </div>
  )
}

export function LiveViewDialog({ device, open, onClose }: { device: Device; open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title={`Live view: ${device.name}`} wide>
      <LiveBody device={device} onClose={onClose} />
    </Dialog>
  )
}

export function LiveViewButton({ device, onOpen }: { device: Device; onOpen: () => void }) {
  const caps = device.caps ?? {}
  if (!caps.live_view) return null
  const blocked = device.status === 'offline' || device.locked
  return (
    <Button icon={<Eye size={17} aria-hidden="true" />} onClick={onOpen} disabled={blocked} title={blocked ? 'The device must be online and unlocked.' : undefined}>
      Live view
    </Button>
  )
}
