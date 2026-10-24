import { Camera } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ScreenGrid } from '../components/ScreenGrid'
import { EmptyState, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { useNow } from '../lib/hooks'
import { useHub } from '../lib/store'
import { useSnapshots } from '../lib/useSnapshots'

export function Screens() {
  const { devices } = useHub()
  const now = useNow(60_000)
  const [deviceId, setDeviceId] = useState('')
  const [days, setDays] = useState<number | null>(null)
  const shots = useSnapshots(deviceId || undefined, 24)
  const names = new Map(devices.map((d) => [d.device_id, d.name]))

  useEffect(() => {
    api.settings().then((s) => setDays(s.retention.snapshots_days)).catch(() => undefined)
  }, [])

  return (
    <div className="page">
      <header className="page__head">
        <div>
          <h1 className="page__title">Screens</h1>
          <p className="muted">
            Screenshots are stored only on your hub{days ? ` and deleted after ${days} days` : ''}. Tap one to see it larger.
          </p>
        </div>
        <label className="selectwrap">
          <span className="sr-only">Show screenshots from</span>
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

      {shots.loading ? (
        <Skeleton lines={4} />
      ) : shots.error ? (
        <p className="notice notice--bad">{shots.error}</p>
      ) : shots.items.length === 0 ? (
        <EmptyState icon={<Camera size={26} />} title="No screenshots yet">
          Windows PCs set up for a child send one every few minutes. You can ask any device for one from its page.
        </EmptyState>
      ) : (
        <ScreenGrid items={shots.items} deviceName={(id) => names.get(id) ?? 'Removed device'} hasMore={shots.hasMore} onLoadMore={shots.loadMore} onDelete={shots.remove} onImageError={() => void shots.refetch()} now={now} />
      )}
    </div>
  )
}
