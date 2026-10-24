import { History } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Timeline } from '../components/Timeline'
import { Button, EmptyState, Skeleton } from '../components/ui'
import { useNow } from '../lib/hooks'
import { useHub } from '../lib/store'

const FILTERS = [
  { id: 'all', label: 'Everything', types: null },
  { id: 'blocked', label: 'Blocked sites', types: ['dns_block'] },
  { id: 'alerts', label: 'Alerts', types: ['vpn_attempt', 'device_went_dark', 'agent_stopped', 'enforcement_notice'] },
  { id: 'screens', label: 'Screenshots', types: ['screenshot'] },
  { id: 'actions', label: 'Your actions', types: ['remote_action', 'device_locked', 'device_unlocked', 'policy_sync', 'device_paired'] },
] as const

export function Activity() {
  const { events, devices, categoryLabels, loaded, loadMoreEvents } = useHub()
  const now = useNow(60_000)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all')
  const [deviceId, setDeviceId] = useState('')
  const [more, setMore] = useState(true)
  const [busy, setBusy] = useState(false)

  const visible = useMemo(() => {
    const types = FILTERS.find((f) => f.id === filter)?.types
    return events.filter((e) => (!types || (types as readonly string[]).includes(e.type)) && (!deviceId || e.device_id === deviceId))
  }, [events, filter, deviceId])

  return (
    <div className="page page--narrow">
      <header className="page__head">
        <div>
          <h1 className="page__title">Activity</h1>
          <p className="muted">Everything that happened on your family's devices, newest first.</p>
        </div>
        <label className="selectwrap">
          <span className="sr-only">Show activity for</span>
          <select className="input" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
            <option value="">All devices</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="chips chips--scroll" role="group" aria-label="Type of activity">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className={`togglechip ${filter === f.id ? 'is-on' : ''}`} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>

      <section className="panel">
        {!loaded ? (
          <Skeleton lines={5} />
        ) : visible.length === 0 ? (
          <EmptyState icon={<History size={26} />} title="Nothing to show">
            {filter === 'all' && !deviceId ? 'When something happens on a device it appears here straight away.' : 'Nothing matches those filters yet.'}
          </EmptyState>
        ) : (
          <Timeline events={visible} devices={devices} labels={categoryLabels} now={now} />
        )}
        {loaded && more && events.length >= 50 && (
          <div className="center">
            <Button
              busy={busy}
              onClick={async () => {
                setBusy(true)
                const count = await loadMoreEvents(deviceId ? { device_id: deviceId } : {})
                setBusy(false)
                if (count === 0) setMore(false)
              }}
            >
              Show older
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
