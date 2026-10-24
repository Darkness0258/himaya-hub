import { Eye, EyeOff, KeyRound } from 'lucide-react'
import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { StarMark, StarPattern, Wordmark } from '../components/Brand'
import { Button } from '../components/ui'
import { api, ApiError } from '../lib/api'

export function Login({ notice, onSuccess }: { notice?: string; onSuccess: (key: string, remember: boolean) => void }) {
  const [key, setKey] = useState('')
  const [show, setShow] = useState(false)
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputId = useId()

  async function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) {
      setError('Paste your admin key first.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.checkKey(trimmed)
      onSuccess(trimmed, remember)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setError("That key isn't right. Copy it again from the hub's window or from data/admin_key.txt.")
      else setError(e instanceof Error ? e.message : 'Could not sign in.')
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <section className="login__art" aria-hidden="true">
        <StarPattern />
        <div className="login__art-copy">
          <StarMark size={72} />
          <p className="login__tagline">A quiet place to look after the people you love online.</p>
        </div>
      </section>

      <main className="login__panel">
        <div className="login__brand">
          <StarMark size={34} />
          <Wordmark />
        </div>
        <h1 className="login__title">Sign in to your hub</h1>
        <p className="login__lead">Your family's data stays on the hub in your home. Enter its admin key to continue.</p>

        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}

        <form onSubmit={submit} className="login__form" noValidate>
          <div className="field">
            <label className="field__label" htmlFor={inputId}>
              Admin key
            </label>
            <div className="inputgroup">
              <KeyRound size={18} aria-hidden="true" />
              <input
                id={inputId}
                className="input input--bare"
                type={show ? 'text' : 'password'}
                value={key}
                onChange={(e) => {
                  setKey(e.target.value)
                  setError('')
                }}
                placeholder="hma_..."
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? `${inputId}-err` : undefined}
              />
              <button type="button" className="inputgroup__btn" onClick={() => setShow((v) => !v)} aria-label={show ? 'Hide key' : 'Show key'}>
                {show ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
              </button>
            </div>
            {error && (
              <p id={`${inputId}-err`} className="field__error" role="alert">
                {error}
              </p>
            )}
          </div>

          <label className="check">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            <span>Keep me signed in on this device</span>
          </label>

          <Button type="submit" variant="primary" busy={busy}>
            Sign in
          </Button>
        </form>

        <details className="help">
          <summary>Where do I find my key?</summary>
          <div className="help__body">
            <p>The first time the hub starts it prints the key in its window and saves it in a file.</p>
            <ul>
              <li>
                On this computer: open <code>hub/data/admin_key.txt</code>.
              </li>
              <li>
                Using Docker: run <code>docker compose exec himaya-hub cat /app/data/admin_key.txt</code>.
              </li>
              <li>
                On Render: open your service, then Environment, then <code>HIMAYA_ADMIN_KEY</code>.
              </li>
              <li>
                Lost it? Run <code>python main.py --reset-admin-key</code> in the hub folder.
              </li>
            </ul>
          </div>
        </details>
      </main>
    </div>
  )
}
