import { Camera, CircleCheck, Pause, Play, Plus, Smartphone } from 'lucide-react'
import { useState } from 'react'
import { ActivityChart } from '../components/ActivityChart'
import { StarPattern } from '../components/Brand'
import { DeviceRow } from '../components/DeviceRow'
import { EventIcon } from '../components/EventIcon'
import { Button, EmptyState, LinkButton, Skeleton } from '../components/ui'
import { blocksSinceMidnight, eventView, needsAttention, summarizeFamily } from '../lib/describe'
import { timeAgo } from '../lib/format'
import { greeting, routeHref, useNow, useResolvedTheme } from '../lib/hooks'
import { useHub, useRunAction } from '../lib/store'
import { useToast } from '../lib/toast'
import { useSnapshots } from '../lib/useSnapshots'

export function Home() {
  const { devices, events, stats, loaded, loadError, categoryLabels } = useHub()
  const now = useNow(30_000)
  const theme = useResolvedTheme()
  const run = useRunAction()
  const toast = useToast()
  const shots = useSnapshots(undefined, 6)
  const [bulkBusy, setBulkBusy] = useState(false)

  const summary = summarizeFamily(devices, events, { now, blocksToday: blocksSinceMidnight(stats, now) })
  const attention = needsAttention(events, devices, now).slice(0, 5)
  const names = new Map(devices.map((d) => [d.device_id, d.name]))
  const children = devices.filter((d) => d.owner_type === 'child')
  const anyRunning = children.some((d) => !d.paused)
  const anyPaused = children.some((d) => d.paused)
  const topMax = Math.max(1, ...(stats?.top_blocked.map((b) => b.count) ?? [1]))

  async function setAllPaused(pause: boolean) {
    setBulkBusy(true)
    const targets = children.filter((d) => d.paused !== pause)
    const results = await Promise.all(targets.map((d) => run(d.device_id, pause ? 'pause' : 'unpause')))
    setBulkBusy(false)
    const ok = results.filter(Boolean).length
    if (ok > 0) toast.push(`${pause ? 'Paused' : 'Resumed'} ${ok} ${ok === 1 ? 'device' : 'devices'}.`, 'ok')
  }

  return (
    <div className="page">
      <header className="hero" data-tone={summary.tone}>
        <StarPattern />
        <div className="hero__inner">
          <p className="hero__greeting">{greeting(now)}</p>
          {loaded ? (
            <>
              <h1 className="hero__headline">{summary.headline}</h1>
              <p className="hero__detail">{summary.detail}</p>
            </>
          ) : (
            <>
              <h1 className="hero__headline hero__headline--wait">{loadError ? "Couldn't load your family." : 'Checking in on everyone.'}</h1>
              <p className="hero__detail">{loadError ?? 'One moment.'}</p>
            </>
          )}
          <div className="hero__actions">
            {loaded && devices.length === 0 && (
              <LinkButton href={routeHref({ view: 'enroll' })} variant="primary" icon={<Plus size={18} aria-hidden="true" />}>
                Add your first device
              </LinkButton>
            )}
            {children.length > 0 && anyRunning && (
              <Button variant="secondary" busy={bulkBusy} icon={<Pause size={17} aria-hidden="true" />} onClick={() => setAllPaused(true)}>
                Pause all children's devices
              </Button>
            )}
            {children.length > 0 && anyPaused && (
              <Button variant="primary" busy={bulkBusy} icon={<Play size={17} aria-hidden="true" />} onClick={() => setAllPaused(false)}>
                Resume all
              </Button>
            )}
          </div>
        </div>
      </header>

      <div className="home-grid">
        <div className="home-col">
        <section className="panel home-grid__devices" aria-labelledby="h-devices">
          <header className="panel__head">
            <h2 id="h-devices" className="panel__title">
              Devices
            </h2>
            <a className="link" href={routeHref({ view: 'devices' })}>
              Manage
            </a>
          </header>
          {!loaded ? (
            <Skeleton lines={3} />
          ) : devices.length === 0 ? (
            <EmptyState icon={<Smartphone size={26} />} title="No devices yet" action={<LinkButton href={routeHref({ view: 'enroll' })} variant="primary" icon={<Plus size={18} aria-hidden="true" />}>Add a device</LinkButton>}>
              Add a Windows PC or an Android phone and it will show up here within seconds.
            </EmptyState>
          ) : (
            <ul className="rows">
              {devices.map((device) => (
                <DeviceRow key={device.device_id} device={device} now={now} quickActions />
              ))}
            </ul>
          )}
        </section>
        <section className="panel home-grid__screens" aria-labelledby="h-screens">
          <header className="panel__head">
            <h2 id="h-screens" className="panel__title">
              Latest screens
            </h2>
            <a className="link" href={routeHref({ view: 'screens' })}>
              See all
            </a>
          </header>
          {shots.loading ? (
            <Skeleton lines={2} />
          ) : shots.items.length === 0 ? (
            <EmptyState icon={<Camera size={26} />} title="No screenshots yet">
              Windows PCs for children send one every few minutes once they are set up. You can also ask for one from a device page.
            </EmptyState>
          ) : (
            <ul className="thumbs">
              {shots.items.map((item) => (
                <li key={item.id}>
                  <a href={routeHref({ view: 'screens' })} aria-label={`Screenshot from ${names.get(item.device_id) ?? 'a device'}, ${timeAgo(item.timestamp, now)}`}>
                    <img src={item.url} alt="" loading="lazy" onError={() => void shots.refetch()} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
        </div>
        <div className="home-col">
        <section className="panel home-grid__attention" aria-labelledby="h-attention">
          <header className="panel__head">
            <h2 id="h-attention" className="panel__title">
              Needs your attention
            </h2>
            <a className="link" href={routeHref({ view: 'activity' })}>
              All activity
            </a>
          </header>
          {attention.length === 0 ? (
            <EmptyState icon={<CircleCheck size={26} />} title="Nothing right now">
              VPNs, devices that go quiet and stopped agents show up here.
            </EmptyState>
          ) : (
            <ul className="rows">
              {attention.map((event) => {
                const view = eventView(event, categoryLabels)
                const known = names.has(event.device_id)
                return (
                  <li key={event.id} className="row row--flat">
                    <a className="row__main" href={known ? routeHref({ view: 'devices', deviceId: event.device_id, tab: 'activity' }) : routeHref({ view: 'activity' })}>
                      <EventIcon icon={view.icon} tone={view.tone} />
                      <span className="row__text">
                        <span className="row__name">{view.title}</span>
                        <span className="row__sub">
                          {names.get(event.device_id) ?? 'A device'}
                          {view.detail ? `: ${view.detail}` : ''}
                        </span>
                      </span>
                      <span className="row__time">{timeAgo(event.timestamp, now)}</span>
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
        <section className="panel home-grid__chart" aria-labelledby="h-chart">
          <header className="panel__head">
            <h2 id="h-chart" className="panel__title">
              The last 24 hours
            </h2>
          </header>
          {stats ? <ActivityChart buckets={stats.histogram} themeKey={theme} /> : <Skeleton lines={4} />}
          {stats && stats.top_blocked.length > 0 && (
            <div className="topblocked">
              <h3 className="topblocked__title">Most blocked</h3>
              <ul>
                {stats.top_blocked.map((item) => (
                  <li key={item.host}>
                    <span className="topblocked__host">{item.host}</span>
                    <span className="topblocked__bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(6, (item.count / topMax) * 100)}%` }} />
                    </span>
                    <span className="topblocked__count">{item.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
        </div>
      </div>
    </div>
  )
}
