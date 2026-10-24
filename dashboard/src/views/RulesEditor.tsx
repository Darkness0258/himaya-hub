import { BedDouble, Check } from 'lucide-react'
import { useEffect, useId, useMemo, useState } from 'react'
import { Button, Segmented, Skeleton, Switch, TagInput } from '../components/ui'
import { api } from '../lib/api'
import { categoryLabel } from '../lib/describe'
import { diffRules, intervalOptions, toDraft } from '../lib/rules'
import type { RulesDraft } from '../lib/rules'
import { useHub } from '../lib/store'
import { useToast } from '../lib/toast'
import type { Device, Rules } from '../lib/types'

export function RulesEditor({ device }: { device: Device }) {
  const { categories } = useHub()
  const toast = useToast()
  const [rules, setRules] = useState<Rules | null>(null)
  const [draft, setDraft] = useState<RulesDraft | null>(null)
  const [loadError, setLoadError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)
  const [timezone, setTimezone] = useState('')
  const sectionId = useId()

  useEffect(() => {
    let alive = true
    api
      .rules(device.device_id)
      .then((loaded) => {
        if (!alive) return
        setRules(loaded)
        setDraft(toDraft(loaded))
      })
      .catch((e: unknown) => alive && setLoadError(e instanceof Error ? e.message : 'Could not load the rules.'))
    api.settings().then((s) => alive && setTimezone(s.timezone)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [device.device_id])

  const patch = useMemo(() => (rules && draft ? diffRules(rules, draft) : {}), [rules, draft])
  const dirty = Object.keys(patch).length > 0

  const categoryOptions = useMemo(() => {
    const known = new Map(categories.map((c) => [c.name, c]))
    for (const name of draft?.categories ?? []) if (!known.has(name)) known.set(name, { name, label: categoryLabel(name), count: 0 })
    return [...known.values()]
  }, [categories, draft?.categories])

  if (loadError) return <p className="notice notice--bad">{loadError}</p>
  if (!rules || !draft) return <Skeleton lines={6} />

  const update = (changes: Partial<RulesDraft>) => {
    setDraft({ ...draft, ...changes })
    setSaveError('')
  }

  async function save() {
    if (!dirty) return
    setSaving(true)
    setSaveError('')
    try {
      const saved = await api.saveRules(device.device_id, patch)
      setRules(saved)
      setDraft(toDraft(saved))
      toast.push(`Rules saved. ${device.name} picks them up within seconds when it is online.`, 'ok')
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  const sameBedtimeTimes = draft.bedtime && draft.start === draft.end
  const adult = device.owner_type === 'adult'

  return (
    <div className="rules">
      <fieldset className="ruleset">
        <legend>Blocked categories</legend>
        <p className="hint">Whole groups of websites. Tap to turn a group on or off.</p>
        <div className="chips" role="group" aria-label="Blocked categories">
          {categoryOptions.map((category) => {
            const on = draft.categories.includes(category.name)
            return (
              <button
                key={category.name}
                type="button"
                className={`togglechip ${on ? 'is-on' : ''}`}
                aria-pressed={on}
                onClick={() => update({ categories: on ? draft.categories.filter((c) => c !== category.name) : [...draft.categories, category.name] })}
                title={category.count ? `${category.count} websites in this group` : undefined}
              >
                {on && <Check size={15} aria-hidden="true" />}
                {category.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <fieldset className="ruleset">
        <legend>Also block these websites</legend>
        <TagInput label="Websites to block" values={draft.blocked} onChange={(blocked) => update({ blocked })} placeholder="Type a website, like example.com" hint="Blocks the site and everything under it. Press Enter or comma after each one." />
      </fieldset>

      <fieldset className="ruleset">
        <legend>Always allow</legend>
        <TagInput label="Websites to always allow" values={draft.allowed} onChange={(allowed) => update({ allowed })} placeholder="Exceptions, like school.example.org" hint="Exceptions win over everything above, even a blocked category." />
      </fieldset>

      <fieldset className="ruleset" aria-labelledby={`${sectionId}-bed`}>
        <legend id={`${sectionId}-bed`}>Bedtime</legend>
        <Switch
          checked={draft.bedtime}
          onChange={(bedtime) => update({ bedtime })}
          label="Turn the internet off at night"
          hint={`During bedtime every website is blocked and the device pauses its internet.${timezone ? ` Uses the hub's time zone (${timezone}).` : ''}`}
        />
        <div className={`timepair ${draft.bedtime ? '' : 'is-off'}`}>
          <label>
            <span className="field__label">From</span>
            <input className="input" type="time" step={300} value={draft.start} disabled={!draft.bedtime} onChange={(e) => update({ start: e.target.value })} />
          </label>
          <label>
            <span className="field__label">Until</span>
            <input className="input" type="time" step={300} value={draft.end} disabled={!draft.bedtime} onChange={(e) => update({ end: e.target.value })} />
          </label>
        </div>
        {sameBedtimeTimes && <p className="field__error">From and until are the same, so bedtime would never start. Pick two different times.</p>}
        {rules.bedtime_active && (
          <p className="notice notice--info">
            <BedDouble size={16} aria-hidden="true" /> Bedtime is active right now.
          </p>
        )}
      </fieldset>

      <fieldset className="ruleset">
        <legend>Screenshots</legend>
        <Segmented label="Screenshot interval" options={intervalOptions(draft.interval)} value={draft.interval} onChange={(interval) => update({ interval })} />
        <p className="hint">
          {device.platform === 'android'
            ? 'Android asks the child to approve every screenshot, so a schedule does not apply to phones. Use "Screenshot now" on the device page.'
            : adult
              ? "This is an adult's device. Only turn screenshots on if they have agreed to it."
              : 'How often a screenshot is sent to your hub while the PC is unlocked. They are stored only on your hub and removed automatically after a while.'}
        </p>
      </fieldset>

      {(dirty || saveError) && (
        <div className="savebar" role="region" aria-label="Unsaved changes">
          <p>{saveError ? <span className="field__error">{saveError}</span> : 'You have unsaved changes.'}</p>
          <div className="savebar__actions">
            <Button variant="ghost" onClick={() => { setDraft(toDraft(rules)); setSaveError('') }} disabled={saving}>
              Discard
            </Button>
            <Button variant="primary" busy={saving} disabled={sameBedtimeTimes} onClick={save}>
              Save changes
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
