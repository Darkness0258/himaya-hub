import { ArrowLeft, Camera, Check, CircleDashed, Copy, Lock, LockOpen, MessageSquareText, Pause, Play, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { DeviceIcon } from '../components/DeviceIcon'
import { ScreenGrid } from '../components/ScreenGrid'
import { Timeline } from '../components/Timeline'
import { Button, ConfirmDialog, Dialog, EmptyState, Segmented, Skeleton, StateChip } from '../components/ui'
import { api } from '../lib/api'
import { capabilityNotes, lastSeenText, PLATFORM_LABEL } from '../lib/describe'
import { dateTime } from '../lib/format'
import { navigate, routeHref, useNow, useRoute } from '../lib/hooks'
import type { DeviceTab } from '../lib/hooks'
import { useHub, useRunAction } from '../lib/store'
import { useToast } from '../lib/toast'
import type { Device } from '../lib/types'
import { useSnapshots } from '../lib/useSnapshots'
import { LiveViewButton, LiveViewDialog } from './LiveView'
import { RulesEditor } from './RulesEditor'

const TABS: { id: DeviceTab; label: string }[] = [
  { id: 'rules', label: 'Rules' },
  { id: 'screens', label: 'Screens' },
  { id: 'activity', label: 'Activity' },
  { id: 'details', label: 'Details' },
]

const QUICK_MESSAGES = ['Dinner is ready', 'Time to wrap up', 'Please come downstairs', 'Homework time']

function MessageDialog({ device, open, onClose }: { device: Device; open: boolean; onClose: () => void }) {
  const run = useRunAction()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  async function send() {
    setBusy(true)
    const ok = await run(device.device_id, 'push_notification', { message: text.trim() }, `Message sent to ${device.name}.`)
    setBusy(false)
    if (ok) {
      setText('')
      onClose()
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Send a message to ${device.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={!text.trim()} onClick={send}>
            Send message
          </Button>
        </>
      }
    >
      <p className="hint">It appears on the screen straight away if the device is online, or as soon as it comes back.</p>
      <div className="chips">
        {QUICK_MESSAGES.map((message) => (
          <button key={message} type="button" className="togglechip" onClick={() => setText(message)}>
            {message}
          </button>
        ))}
      </div>
      <div className="field">
        <label className="field__label" htmlFor="msg">
          Message
        </label>
        <textarea id="msg" className="input" rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a short message" />
        <p className="hint hint--right">{text.length} / 500</p>
      </div>
    </Dialog>
  )
}

function CloseAppDialog({ device, open, onClose }: { device: Device; open: boolean; onClose: () => void }) {
  const run = useRunAction()
  const [app, setApp] = useState('')
  const [busy, setBusy] = useState(false)
  const android = device.platform === 'android'
  async function close() {
    setBusy(true)
    const ok = await run(device.device_id, 'force_close_app', { app: app.trim() }, `Asked ${device.name} to close ${app.trim()}.`)
    setBusy(false)
    if (ok) {
      setApp('')
      onClose()
    }
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Close an app on ${device.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy} disabled={!app.trim()} onClick={close}>
            Close the app
          </Button>
        </>
      }
    >
      <div className="field">
        <label className="field__label" htmlFor="app">
          {android ? 'App package name' : 'Program name'}
        </label>
        <input id="app" className="input" value={app} onChange={(e) => setApp(e.target.value)} placeholder={android ? 'com.roblox.client' : 'chrome  or  Roblox'} autoCapitalize="none" spellCheck={false} />
        <p className="hint">{android ? 'Android only closes apps that are running in the background.' : 'The name shown in Task Manager, without ".exe". Unsaved work in that program is lost.'}</p>
      </div>
    </Dialog>
  )
}

function CapabilityStatus({ status }: { status: 'yes' | 'partial' | 'no' }) {
  if (status === 'yes')
    return (
      <span className="cap cap--yes">
        <Check size={15} aria-hidden="true" /> Works
      </span>
    )
  if (status === 'partial')
    return (
      <span className="cap cap--partial">
        <CircleDashed size={15} aria-hidden="true" /> Partly
      </span>
    )
  return (
    <span className="cap cap--no">
      <X size={15} aria-hidden="true" /> Not available
    </span>
  )
}

function DetailsPanel({ device }: { device: Device }) {
  const toast = useToast()
  const run = useRunAction()
  const { refresh, applyDevice } = useHub()
  const [name, setName] = useState(device.name)
  const [renaming, setRenaming] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [eraseOpen, setEraseOpen] = useState(false)
  const [eraseText, setEraseText] = useState('')
  const [busy, setBusy] = useState(false)
  const [rulesInterval, setRulesInterval] = useState<number | undefined>(undefined)

  useEffect(() => {
    let alive = true
    api.rules(device.device_id).then((r) => alive && setRulesInterval(r.snapshot_interval_s)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [device.device_id])

  const notes = capabilityNotes(device, rulesInterval)

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.push(`${what} copied.`, 'ok')
    } catch {
      toast.push('Copy is blocked in this browser. Select the text and copy it by hand.', 'warn')
    }
  }

  async function rename() {
    if (!name.trim() || name.trim() === device.name) return
    setRenaming(true)
    try {
      applyDevice(await api.renameDevice(device.device_id, { name: name.trim() }))
      toast.push('Renamed.', 'ok')
    } catch (e) {
      toast.push(e instanceof Error ? e.message : 'Could not rename.', 'bad')
    } finally {
      setRenaming(false)
    }
  }

  async function setOwner(owner: 'child' | 'adult') {
    try {
      applyDevice(await api.renameDevice(device.device_id, { owner_type: owner }))
      toast.push(owner === 'adult' ? 'Marked as an adult device. Review its screenshot setting under Rules.' : 'Marked as a child device.', 'ok')
    } catch (e) {
      toast.push(e instanceof Error ? e.message : 'Could not change that.', 'bad')
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await api.deleteDevice(device.device_id)
      await refresh()
      toast.push(`${device.name} was removed.`, 'ok')
      navigate({ view: 'devices' })
    } catch (e) {
      toast.push(e instanceof Error ? e.message : 'Could not remove it.', 'bad')
      setBusy(false)
    }
  }

  async function erase() {
    setBusy(true)
    const ok = await run(device.device_id, 'wipe', { confirm: device.device_id }, `Erase requested for ${device.name}.`)
    setBusy(false)
    if (ok) {
      setEraseOpen(false)
      setEraseText('')
    }
  }

  return (
    <div className="details">
      <dl className="facts">
        <div>
          <dt>Device ID</dt>
          <dd>
            <code>{device.device_id}</code>
            <button type="button" className="iconbtn iconbtn--sm" onClick={() => copy(device.device_id, 'Device ID')} aria-label="Copy device ID">
              <Copy size={15} aria-hidden="true" />
            </button>
          </dd>
        </div>
        <div>
          <dt>Kind</dt>
          <dd>{PLATFORM_LABEL[device.platform]}</dd>
        </div>
        <div>
          <dt>Network address</dt>
          <dd>{device.ip ?? 'Unknown'}</dd>
        </div>
        <div>
          <dt>Added</dt>
          <dd>{dateTime(device.created_at)}</dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd>{device.last_seen ? dateTime(device.last_seen) : 'Not yet'}</dd>
        </div>
        <div>
          <dt>Himaya version</dt>
          <dd>{device.agent_version ?? 'Unknown'}</dd>
        </div>
      </dl>

      <section className="subsection">
        <h3 className="subsection__title">Who uses this device</h3>
        <Segmented
          label="Who uses this device"
          options={[
            { value: 'child', label: 'A child' },
            { value: 'adult', label: 'An adult' },
          ]}
          value={device.owner_type}
          onChange={setOwner}
        />
        <p className="hint">Adults are only monitored by agreement: no screenshots and no website blocking unless you turn them on.</p>
      </section>

      <section className="subsection">
        <h3 className="subsection__title">What Himaya can do here</h3>
        <ul className="caps">
          {notes.map((note) => (
            <li key={note.label}>
              <div>
                <p className="caps__label">{note.label}</p>
                <p className="hint">{note.note}</p>
              </div>
              <CapabilityStatus status={note.status} />
            </li>
          ))}
        </ul>
      </section>

      <section className="subsection">
        <h3 className="subsection__title">Name</h3>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            void rename()
          }}
        >
          <label className="sr-only" htmlFor="rename">
            Device name
          </label>
          <input id="rename" className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" busy={renaming} disabled={!name.trim() || name.trim() === device.name}>
            Save name
          </Button>
        </form>
      </section>

      <section className="subsection danger">
        <h3 className="subsection__title">Danger zone</h3>
        <div className="danger__row">
          <div>
            <p className="caps__label">Remove this device</p>
            <p className="hint">Takes it off your list and deletes its history and screenshots from the hub.</p>
          </div>
          <Button variant="danger" onClick={() => setRemoveOpen(true)}>
            Remove
          </Button>
        </div>
        {device.platform === 'android' && (
          <div className="danger__row">
            <div>
              <p className="caps__label">Erase this phone</p>
              <p className="hint">For a lost or stolen phone. It restores factory settings and cannot be undone.</p>
            </div>
            <Button variant="danger" onClick={() => setEraseOpen(true)}>
              Erase
            </Button>
          </div>
        )}
      </section>

      <ConfirmDialog open={removeOpen} title={`Remove ${device.name}?`} confirmLabel="Remove device" danger busy={busy} onClose={() => setRemoveOpen(false)} onConfirm={remove}>
        <p>Himaya stops watching this device and forgets its history. The program on the device will notice it was removed and let go of any lock or internet pause.</p>
        <p className="hint">{device.platform === 'windows' ? 'To remove the program itself, run uninstall.ps1 from the HimayaAgent folder on that PC.' : 'To remove the app itself, uninstall Himaya Agent from the phone.'}</p>
      </ConfirmDialog>

      <ConfirmDialog open={eraseOpen} title={`Erase ${device.name}?`} confirmLabel="Erase phone" danger busy={busy} disabled={eraseText.trim().toLowerCase() !== device.name.trim().toLowerCase()} onClose={() => { setEraseOpen(false); setEraseText('') }} onConfirm={erase}>
        <p>Everything on the phone is deleted: photos, messages, accounts. This is meant for a lost or stolen phone.</p>
        <div className="field">
          <label className="field__label" htmlFor="erase-confirm">
            Type the phone's name, <strong>{device.name}</strong>, to confirm
          </label>
          <input id="erase-confirm" className="input" value={eraseText} onChange={(e) => setEraseText(e.target.value)} autoComplete="off" />
        </div>
      </ConfirmDialog>
    </div>
  )
}

function DeviceScreens({ device }: { device: Device }) {
  const shots = useSnapshots(device.device_id, 18)
  const now = useNow(60_000)
  if (shots.loading) return <Skeleton lines={3} />
  if (shots.items.length === 0)
    return (
      <EmptyState icon={<Camera size={26} />} title="No screenshots yet">
        {device.platform === 'android' ? 'Ask for one with "Screenshot now". The child is asked to approve it on the phone.' : 'Screenshots arrive on the schedule you set under Rules, or ask for one with "Screenshot now".'}
      </EmptyState>
    )
  return <ScreenGrid items={shots.items} deviceName={() => device.name} hasMore={shots.hasMore} onLoadMore={shots.loadMore} onDelete={shots.remove} onImageError={() => void shots.refetch()} now={now} />
}

function DeviceActivity({ device }: { device: Device }) {
  const { events, devices, categoryLabels, loadMoreEvents } = useHub()
  const now = useNow(60_000)
  const [more, setMore] = useState(true)
  const [busy, setBusy] = useState(false)
  const mine = events.filter((e) => e.device_id === device.device_id)
  if (mine.length === 0) return <EmptyState icon={<Camera size={26} />} title="Nothing yet">Blocked websites, alerts and your actions on this device will be listed here.</EmptyState>
  return (
    <>
      <Timeline events={mine} devices={devices} labels={categoryLabels} now={now} showDevice={false} />
      {more && (
        <div className="center">
          <Button
            busy={busy}
            onClick={async () => {
              setBusy(true)
              const count = await loadMoreEvents({ device_id: device.device_id })
              setBusy(false)
              if (count === 0) setMore(false)
            }}
          >
            Show older
          </Button>
        </div>
      )}
    </>
  )
}

export function DeviceDetail({ device }: { device: Device }) {
  const route = useRoute()
  const run = useRunAction()
  const now = useNow(30_000)
  const [busy, setBusy] = useState('')
  const [messageOpen, setMessageOpen] = useState(false)
  const [closeOpen, setCloseOpen] = useState(false)
  const [liveOpen, setLiveOpen] = useState(false)
  const offline = device.status === 'offline'
  const later = offline ? ' It takes effect when the device is back online.' : ''

  async function act(key: string, action: 'lock' | 'unlock' | 'pause' | 'unpause' | 'snapshot', text: string) {
    setBusy(key)
    await run(device.device_id, action, {}, text + (action === 'snapshot' ? '' : later))
    setBusy('')
  }

  return (
    <article className="detail" aria-labelledby="detail-name">
      <a className="detail__back" href={routeHref({ view: 'devices' })}>
        <ArrowLeft size={18} aria-hidden="true" /> All devices
      </a>
      <header className="detail__head">
        <DeviceIcon device={device} size={30} />
        <div className="detail__title">
          <h2 id="detail-name">{device.name}</h2>
          <p className="muted">
            {PLATFORM_LABEL[device.platform]}
            {device.owner_type === 'adult' ? ', adult device' : ''}. {lastSeenText(device, now)}.
          </p>
        </div>
        <StateChip device={device} />
      </header>

      <div className="actions" role="group" aria-label={`Actions for ${device.name}`}>
        <Button variant={device.locked ? 'primary' : 'secondary'} busy={busy === 'lock'} icon={device.locked ? <LockOpen size={17} aria-hidden="true" /> : <Lock size={17} aria-hidden="true" />} onClick={() => act('lock', device.locked ? 'unlock' : 'lock', device.locked ? `${device.name} unlocked.` : `${device.name} locked.`)}>
          {device.locked ? 'Unlock screen' : 'Lock screen'}
        </Button>
        <Button variant={device.paused ? 'primary' : 'secondary'} busy={busy === 'pause'} icon={device.paused ? <Play size={17} aria-hidden="true" /> : <Pause size={17} aria-hidden="true" />} onClick={() => act('pause', device.paused ? 'unpause' : 'pause', device.paused ? 'Internet resumed.' : 'Internet paused.')}>
          {device.paused ? 'Resume internet' : 'Pause internet'}
        </Button>
        <Button icon={<MessageSquareText size={17} aria-hidden="true" />} onClick={() => setMessageOpen(true)}>
          Send message
        </Button>
        <Button busy={busy === 'snapshot'} icon={<Camera size={17} aria-hidden="true" />} onClick={() => act('snapshot', 'snapshot', device.platform === 'android' ? 'Asked the phone. The child has to approve it.' : 'Screenshot requested.')}>
          Screenshot now
        </Button>
        <LiveViewButton device={device} onOpen={() => setLiveOpen(true)} />
        <Button variant="ghost" icon={<X size={17} aria-hidden="true" />} onClick={() => setCloseOpen(true)}>
          Close an app
        </Button>
      </div>

      <nav className="tabs" role="tablist" aria-label="Device sections">
        {TABS.map((tab) => (
          <a key={tab.id} role="tab" id={`tab-${tab.id}`} aria-selected={route.tab === tab.id} aria-controls="tabpanel" href={routeHref({ view: 'devices', deviceId: device.device_id, tab: tab.id })} className={route.tab === tab.id ? 'is-on' : ''}>
            {tab.label}
          </a>
        ))}
      </nav>
      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${route.tab}`} className="tabpanel">
        {route.tab === 'rules' && <RulesEditor key={device.device_id} device={device} />}
        {route.tab === 'screens' && <DeviceScreens device={device} />}
        {route.tab === 'activity' && <DeviceActivity device={device} />}
        {route.tab === 'details' && <DetailsPanel device={device} />}
      </div>

      <MessageDialog device={device} open={messageOpen} onClose={() => setMessageOpen(false)} />
      <CloseAppDialog device={device} open={closeOpen} onClose={() => setCloseOpen(false)} />
      <LiveViewDialog device={device} open={liveOpen} onClose={() => setLiveOpen(false)} />
    </article>
  )
}
