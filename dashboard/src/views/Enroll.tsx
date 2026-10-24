import { Check, Copy, Monitor, RefreshCw, Smartphone } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button, Segmented } from '../components/ui'
import { api } from '../lib/api'
import { groupPin } from '../lib/format'
import { routeHref, useNow } from '../lib/hooks'
import { useHub } from '../lib/store'
import { useToast } from '../lib/toast'
import type { EnrollInfo } from '../lib/types'

function CopyBox({ text, label }: { text: string; label: string }) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      toast.push('Copy is blocked in this browser. Select the text and copy it by hand.', 'warn')
    }
  }
  return (
    <div className="copybox">
      <code tabIndex={0} aria-label={label}>
        {text}
      </code>
      <Button size="sm" icon={copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />} onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  )
}

export function Enroll() {
  const { devices, loaded } = useHub()
  const toast = useToast()
  const [info, setInfo] = useState<EnrollInfo | null>(null)
  const [fetchedAt, setFetchedAt] = useState(0)
  const [error, setError] = useState('')
  const [kind, setKind] = useState<'lan' | 'internet'>('lan')
  const [platform, setPlatform] = useState<'windows' | 'android'>('windows')
  const [renewing, setRenewing] = useState(false)
  const now = useNow(1000)
  const [baseline, setBaseline] = useState<Set<string> | null>(null)
  if (loaded && baseline === null) setBaseline(new Set(devices.map((d) => d.device_id)))

  const load = useCallback(async () => {
    try {
      setInfo(await api.enrollInfo())
      setFetchedAt(Date.now())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the pairing details.')
    }
  }, [])

  useEffect(() => {
    // The setState calls inside load() run after an await, not synchronously in the effect.
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
    const id = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(id)
  }, [load])

  const remaining = info ? Math.max(0, info.pin_expires_in - Math.floor((now - fetchedAt) / 1000)) : 0
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    if (info && remaining === 0) void load()
  }, [info, remaining, load])

  const added = baseline ? devices.find((d) => !baseline.has(d.device_id)) : undefined

  const url = info?.urls.find((u) => u.kind === kind) ?? info?.urls[0]
  const mm = String(Math.floor(remaining / 60)).padStart(1, '0')
  const ss = String(remaining % 60).padStart(2, '0')

  async function renew() {
    setRenewing(true)
    try {
      const next = await api.regeneratePin()
      setInfo((current) => (current ? { ...current, pin: next.pin, pin_expires_in: next.pin_expires_in } : current))
      setFetchedAt(Date.now())
    } catch (e) {
      toast.push(e instanceof Error ? e.message : 'Could not make a new PIN.', 'bad')
    } finally {
      setRenewing(false)
    }
  }

  return (
    <div className="page page--narrow">
      <header className="page__head">
        <div>
          <h1 className="page__title">Add a device</h1>
          <p className="muted">Pair a Windows PC or an Android phone with your hub. It takes about two minutes.</p>
        </div>
      </header>

      {added && (
        <p className="notice notice--ok" role="status">
          <Check size={17} aria-hidden="true" /> <strong>{added.name}</strong> was added. <a href={routeHref({ view: 'devices', deviceId: added.device_id })}>Open it</a>
        </p>
      )}

      {error && <p className="notice notice--bad">{error}</p>}

      <section className="panel pinpanel" aria-labelledby="pin-title">
        <div>
          <h2 id="pin-title" className="panel__title">
            Pairing PIN
          </h2>
          <p className="hint">Type this on the device when it asks. It works once, then changes.</p>
        </div>
        <p className="pin" aria-live="off" aria-label={info ? `PIN ${info.pin.split('').join(' ')}` : 'PIN loading'}>
          {info ? groupPin(info.pin) : '--- ---'}
        </p>
        <div className="pinpanel__foot">
          <div className="pinbar" role="progressbar" aria-label="Time left on this PIN" aria-valuemin={0} aria-valuemax={900} aria-valuenow={remaining}>
            <span style={{ width: `${Math.min(100, (remaining / 900) * 100)}%` }} />
          </div>
          <p className="hint">
            {remaining > 0 ? `Expires in ${mm}:${ss}` : 'Getting a new PIN'}
          </p>
          <Button variant="ghost" size="sm" busy={renewing} icon={<RefreshCw size={15} aria-hidden="true" />} onClick={renew}>
            New PIN
          </Button>
        </div>
      </section>

      {info && info.urls.length > 1 && (
        <div className="stack-sm">
          <Segmented
            label="Where is the device?"
            options={info.urls.map((u) => ({ value: u.kind, label: u.kind === 'lan' ? 'On this Wi-Fi' : 'Away from home' }))}
            value={url?.kind ?? 'lan'}
            onChange={setKind}
          />
        </div>
      )}

      <div className="stack-sm">
        <Segmented
          label="Kind of device"
          options={[
            { value: 'windows', label: 'Windows PC' },
            { value: 'android', label: 'Android phone' },
          ]}
          value={platform}
          onChange={setPlatform}
        />
      </div>

      {url && platform === 'windows' && (
        <section className="panel" aria-labelledby="win-title">
          <h2 id="win-title" className="panel__title">
            <Monitor size={19} aria-hidden="true" /> On the Windows PC
          </h2>
          <ol className="steps">
            <li>
              Open <strong>PowerShell</strong> on that PC (press the Windows key, type PowerShell, press Enter). A normal window is fine; you do not need Administrator.
            </li>
            <li>
              Paste this line and press Enter:
              <CopyBox text={url.windows_command} label="PowerShell command" />
            </li>
            <li>
              Answer the questions, then type the PIN above. You will see a <strong>Himaya active</strong> icon near the clock when it is done.
            </li>
          </ol>
          <p className="hint">The PC needs Python 3.9 or newer. If it is missing, the script tells you how to install it. The link only works for devices that can reach {new URL(url.url).host}.</p>
        </section>
      )}

      {url && platform === 'android' && (
        <section className="panel" aria-labelledby="and-title">
          <h2 id="and-title" className="panel__title">
            <Smartphone size={19} aria-hidden="true" /> On the Android phone
          </h2>
          <div className="android">
            <img className="qr" src={url.qr_path} alt={`QR code for ${url.mobile_url}`} width={168} height={168} />
            <ol className="steps">
              <li>
                Install the <strong>Himaya Agent</strong> app on the phone (the APK from the project's <code>himaya-mobile</code> build).
              </li>
              <li>Scan this code with the phone's camera, or open this link on the phone:</li>
              <li className="steps__plain">
                <CopyBox text={url.mobile_url} label="Link for the phone" />
              </li>
              <li>The app shows the hub's address. Check it is yours, then type the PIN above.</li>
            </ol>
          </div>
        </section>
      )}

      <aside className="notice notice--info">
        <p>
          <strong>Before you add a device:</strong> tell the person who uses it what Himaya does. Children should know it is there. Adults are only added if they agree, and an adult's device sends no screenshots by default.
        </p>
      </aside>
    </div>
  )
}
