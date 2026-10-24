import { Loader2 } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { normalizeDomain, splitEntries } from '../lib/domain'
import type { Device } from '../lib/types'
import { stateLabel } from '../lib/describe'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'md' | 'sm'
  icon?: ReactNode
  busy?: boolean
}

export function Button({ variant = 'secondary', size = 'md', icon, busy, children, className = '', disabled, type = 'button', ...rest }: ButtonProps) {
  return (
    <button type={type} className={`btn btn--${variant} btn--${size} ${className}`} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <Loader2 className="spin" size={size === 'sm' ? 15 : 17} aria-hidden="true" /> : icon}
      {children && <span>{children}</span>}
    </button>
  )
}

/** A link that looks like a button (navigation, not an action). */
export function LinkButton({ href, variant = 'secondary', size = 'md', icon, children }: { href: string; variant?: Variant; size?: 'md' | 'sm'; icon?: ReactNode; children: ReactNode }) {
  return (
    <a href={href} className={`btn btn--${variant} btn--${size}`}>
      {icon}
      <span>{children}</span>
    </a>
  )
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  active?: boolean
  busy?: boolean
}

export function IconButton({ label, active, busy, children, className = '', type = 'button', disabled, ...rest }: IconButtonProps) {
  return (
    <button type={type} className={`iconbtn ${active ? 'is-active' : ''} ${className}`} aria-label={label} title={label} aria-pressed={active} disabled={disabled || busy} {...rest}>
      {busy ? <Loader2 className="spin" size={18} aria-hidden="true" /> : children}
    </button>
  )
}

export function StateChip({ device, bedtime }: { device: Pick<Device, 'state'>; bedtime?: boolean }) {
  const state = bedtime && device.state === 'online' ? 'bedtime' : device.state
  const label = state === 'bedtime' ? 'Bedtime' : stateLabel(device.state)
  return (
    <span className={`chip chip--${state}`}>
      <span className="chip__dot" aria-hidden="true" />
      {label}
    </span>
  )
}

export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty__icon" aria-hidden="true">
        {icon}
      </div>
      <h3 className="empty__title">{title}</h3>
      {children && <p className="empty__text">{children}</p>}
      {action}
    </div>
  )
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeletons" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${88 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  )
}

export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (value: boolean) => void; label: string; hint?: string }) {
  const id = useId()
  return (
    <div className="switchrow">
      <div>
        <label htmlFor={id} className="switchrow__label">
          {label}
        </label>
        {hint && <p className="hint">{hint}</p>}
      </div>
      <button id={id} type="button" role="switch" aria-checked={checked} className={`switch ${checked ? 'is-on' : ''}`} onClick={() => onChange(!checked)}>
        <span className="switch__thumb" />
      </button>
    </div>
  )
}

export function Segmented<T extends string | number>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (value: T) => void; label: string }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button key={String(option.value)} type="button" role="radio" aria-checked={option.value === value} className={option.value === value ? 'is-on' : ''} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  )
}

/** Native <dialog>: focus is trapped, Esc closes, and focus returns to the trigger. */
export function Dialog({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      className={`dialog ${wide ? 'dialog--wide' : ''}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose()
      }}
    >
      {open && (
        <div className="dialog__body">
          <h2 id={titleId} className="dialog__title">
            {title}
          </h2>
          {children}
          {footer && <div className="dialog__footer">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}

export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, onConfirm, onClose, disabled }: { open: boolean; title: string; children: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean; disabled?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} busy={busy} disabled={disabled}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  )
}

/** Chips + an input that turns what you type or paste into valid, de-duplicated website addresses. */
export function TagInput({ values, onChange, label, placeholder, hint }: { values: string[]; onChange: (values: string[]) => void; label: string; placeholder: string; hint?: string }) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const id = useId()

  const commit = (raw: string): boolean => {
    const entries = splitEntries(raw)
    if (entries.length === 0) return true
    const next = [...values]
    const bad: string[] = []
    for (const entry of entries) {
      const domain = normalizeDomain(entry)
      if (!domain) bad.push(entry)
      else if (!next.includes(domain)) next.push(domain)
    }
    if (next.length > values.length) onChange(next)
    setError(bad.length ? `"${bad[0]}" is not a website address. Try something like example.com.` : '')
    if (bad.length === 0) setText('')
    else setText(bad.join(' '))
    return bad.length === 0
  }

  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <div className="tagbox">
        {values.map((value) => (
          <span key={value} className="tag">
            {value}
            <button type="button" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((v) => v !== value))}>
              ×
            </button>
          </span>
        ))}
        <input
          id={id}
          className="tagbox__input"
          value={text}
          placeholder={values.length === 0 ? placeholder : 'Add another'}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : undefined}
          onChange={(event) => {
            setText(event.target.value)
            if (error) setError('')
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ',' || event.key === ' ') {
              if (text.trim()) {
                event.preventDefault()
                commit(text)
              }
            } else if (event.key === 'Backspace' && !text && values.length) {
              onChange(values.slice(0, -1))
            }
          }}
          onBlur={() => commit(text)}
          onPaste={(event) => {
            const pasted = event.clipboardData.getData('text')
            if (splitEntries(pasted).length > 1) {
              event.preventDefault()
              commit(pasted)
            }
          }}
        />
      </div>
      {error ? (
        <p id={`${id}-err`} className="field__error" role="alert">
          {error}
        </p>
      ) : (
        hint && <p className="hint">{hint}</p>
      )}
    </div>
  )
}
