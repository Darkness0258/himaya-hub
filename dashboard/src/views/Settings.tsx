import { Check, Copy, KeyRound, LogOut } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Button, ConfirmDialog, Dialog, Segmented, Skeleton } from '../components/ui'
import { api, isKeyRemembered, storeKey } from '../lib/api'
import { useTheme } from '../lib/hooks'
import type { ThemePref } from '../lib/hooks'
import { useToast } from '../lib/toast'
import type { HubSettings } from '../lib/types'

export function Settings({ onSignOut }: { onSignOut: () => void }) {
  const toast = useToast()
  const theme = useTheme()
  const [settings, setSettings] = useState<HubSettings | null>(null)
  const [error, setError] = useState('')
  const [publicUrl, setPublicUrl] = useState('')
  const [savingUrl, setSavingUrl] = useState(false)
  const [urlError, setUrlError] = useState('')
  const [rotateOpen, setRotateOpen] = useState(false)
  const [rotating, setRotating] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        setSettings(s)
        setPublicUrl(s.public_url ?? '')
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load the hub settings.'))
  }, [])

  async function saveUrl(event: FormEvent) {
    event.preventDefault()
    setSavingUrl(true)
    setUrlError('')
    try {
      const result = await api.setPublicUrl(publicUrl.trim())
      setPublicUrl(result.public_url ?? '')
      toast.push(result.public_url ? 'Away-from-home address saved.' : 'Away-from-home address removed.', 'ok')
    } catch (e) {
      setUrlError(e instanceof Error ? e.message : 'Could not save that address.')
    } finally {
      setSavingUrl(false)
    }
  }

  async function rotate() {
    setRotating(true)
    try {
      const { admin_key } = await api.rotateAdminKey()
      storeKey(admin_key, isKeyRemembered())
      setNewKey(admin_key)
      setRotateOpen(false)
    } catch (e) {
      toast.push(e instanceof Error ? e.message : 'Could not create a new key.', 'bad')
      setRotateOpen(false)
    } finally {
      setRotating(false)
    }
  }

  const dnsText = !settings
    ? ''
    : settings.dns.running
      ? `Running on port ${settings.dns.port}, forwarding to ${settings.dns.upstream}. ${settings.dns.blocked ?? 0} blocked since the hub started.`
      : settings.dns.error
        ? `Could not start: ${settings.dns.error}`
        : 'Off'

  return (
    <div className="page page--narrow">
      <header className="page__head">
        <div>
          <h1 className="page__title">Settings</h1>
          <p className="muted">How this hub looks, where it is reachable, and who can sign in.</p>
        </div>
      </header>

      <section className="panel" aria-labelledby="s-look">
        <h2 id="s-look" className="panel__title">
          Appearance
        </h2>
        <Segmented<ThemePref>
          label="Colour theme"
          options={[
            { value: 'auto', label: 'Match my device' },
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
          ]}
          value={theme.pref}
          onChange={theme.setPref}
        />
      </section>

      <section className="panel" aria-labelledby="s-hub">
        <h2 id="s-hub" className="panel__title">
          This hub
        </h2>
        {error ? (
          <p className="notice notice--bad">{error}</p>
        ) : !settings ? (
          <Skeleton lines={5} />
        ) : (
          <dl className="facts facts--wide">
            <div>
              <dt>Version</dt>
              <dd>{settings.version}</dd>
            </div>
            <div>
              <dt>Where data is kept</dt>
              <dd>{settings.database === 'postgres' ? 'A PostgreSQL database (Supabase or your own)' : 'A file on the computer running the hub'}</dd>
            </div>
            <div>
              <dt>Address on your Wi-Fi</dt>
              <dd>
                <code>
                  http://{settings.lan_ip}:{settings.port}
                </code>
              </dd>
            </div>
            <div>
              <dt>Time zone for bedtime</dt>
              <dd>{settings.timezone}</dd>
            </div>
            <div>
              <dt>Website filter</dt>
              <dd>{dnsText}</dd>
            </div>
            <div>
              <dt>Finding the hub on Wi-Fi</dt>
              <dd>{settings.discovery.running ? 'On' : 'Off'}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="panel" aria-labelledby="s-url">
        <h2 id="s-url" className="panel__title">
          Away from home
        </h2>
        <p className="hint">If a device needs to reach the hub when it is not on your Wi-Fi, give the hub an address that works from outside: a cloud URL, a DuckDNS name, or a WireGuard address. It is then offered on the Add a device page.</p>
        <form className="inline-form" onSubmit={saveUrl}>
          <label className="sr-only" htmlFor="public-url">
            Address away from home
          </label>
          <input id="public-url" className="input" value={publicUrl} onChange={(e) => { setPublicUrl(e.target.value); setUrlError('') }} placeholder="https://my-hub.example.com" inputMode="url" autoCapitalize="none" spellCheck={false} />
          <Button type="submit" busy={savingUrl}>
            Save
          </Button>
        </form>
        {urlError && <p className="field__error">{urlError}</p>}
        <p className="hint">Leave it empty to remove the address.</p>
      </section>

      <section className="panel" aria-labelledby="s-priv">
        <h2 id="s-priv" className="panel__title">
          What the hub keeps
        </h2>
        <ul className="plainlist">
          <li>
            <strong>Kept:</strong> device names, when they were online, websites that were blocked, VPN alerts, your actions, and screenshots from devices where you turned them on.
          </li>
          <li>
            <strong>Never collected:</strong> what anyone types, camera or microphone, private messages, or browsing history beyond blocked websites.
          </li>
          {settings && (
            <li>
              <strong>Cleaned up automatically:</strong> activity after {settings.retention.events_days} days and screenshots after {settings.retention.snapshots_days} days (at most {settings.retention.snapshots_per_device} per device).
            </li>
          )}
          <li>
            <strong>Stays here:</strong> nothing is sent to Himaya or any other company. Screenshots live only on the hub.
          </li>
        </ul>
      </section>

      <section className="panel" aria-labelledby="s-sec">
        <h2 id="s-sec" className="panel__title">
          Security
        </h2>
        <div className="danger__row">
          <div>
            <p className="caps__label">Admin key</p>
            <p className="hint">
              {settings?.admin_key_source === 'environment' ? 'This key is set by the HIMAYA_ADMIN_KEY setting. Change it there.' : 'Create a new key if you think the old one was seen. The old one stops working at once.'}
            </p>
          </div>
          <Button icon={<KeyRound size={17} aria-hidden="true" />} disabled={settings?.admin_key_source === 'environment'} onClick={() => setRotateOpen(true)}>
            New key
          </Button>
        </div>
        <div className="danger__row">
          <div>
            <p className="caps__label">Sign out</p>
            <p className="hint">You will need the admin key to sign in again on this device.</p>
          </div>
          <Button variant="secondary" icon={<LogOut size={17} aria-hidden="true" />} onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </section>

      <ConfirmDialog open={rotateOpen} title="Create a new admin key?" confirmLabel="Create new key" busy={rotating} onClose={() => setRotateOpen(false)} onConfirm={rotate}>
        <p>Other browsers and phones signed in with the old key will be signed out. Devices that Himaya protects are not affected.</p>
      </ConfirmDialog>

      <Dialog
        open={Boolean(newKey)}
        onClose={() => setNewKey('')}
        title="Your new admin key"
        footer={
          <Button variant="primary" onClick={() => setNewKey('')}>
            I have saved it
          </Button>
        }
      >
        <p>Save it somewhere safe, such as a password manager. This is the only time it is shown here. It is also written to <code>data/admin_key.txt</code> on the hub.</p>
        <div className="copybox">
          <code tabIndex={0}>{newKey}</code>
          <Button
            size="sm"
            icon={copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(newKey)
                setCopied(true)
                window.setTimeout(() => setCopied(false), 1800)
              } catch {
                toast.push('Copy is blocked. Select the key and copy it by hand.', 'warn')
              }
            }}
          >
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
