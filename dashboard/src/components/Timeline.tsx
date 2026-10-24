import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { eventView, groupEvents, groupSummary } from '../lib/describe'
import { clockTime, dayHeading, timeAgo } from '../lib/format'
import { routeHref } from '../lib/hooks'
import type { Device, HubEvent } from '../lib/types'
import { EventIcon } from './EventIcon'

export function Timeline({ events, devices, labels, now, showDevice = true }: { events: HubEvent[]; devices: Device[]; labels: Record<string, string>; now: number; showDevice?: boolean }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const groups = useMemo(() => groupEvents(events), [events])
  const names = new Map(devices.map((d) => [d.device_id, d.name]))
  const headings = groups.map((group) => dayHeading(group.events[0].timestamp, now))

  const deviceLabel = (event: HubEvent) => {
    const known = names.has(event.device_id)
    const name = names.get(event.device_id) ?? (event.device_id.startsWith('network-') ? `Unknown device (${event.device_id.slice(8)})` : 'Removed device')
    return known ? <a href={routeHref({ view: 'devices', deviceId: event.device_id })}>{name}</a> : <span>{name}</span>
  }

  return (
    <ol className="timeline">
      {groups.map((group, index) => {
        const first = group.events[0]
        const showHeading = index === 0 || headings[index - 1] !== headings[index]
        const expanded = open.has(group.key)

        if (group.grouped) {
          const summary = groupSummary(group)
          return (
            <li key={group.key} className="timeline__item">
              {showHeading && <h3 className="timeline__day">{headings[index]}</h3>}
              <div className="timeline__row">
                <EventIcon icon="ban" tone="neutral" />
                <div className="timeline__text">
                  <p className="timeline__title">{summary.title}</p>
                  <p className="timeline__meta">
                    {showDevice && <>{deviceLabel(first)}: </>}
                    {summary.detail}
                  </p>
                  <button
                    type="button"
                    className="timeline__more"
                    aria-expanded={expanded}
                    onClick={() => setOpen((current) => {
                      const next = new Set(current)
                      if (next.has(group.key)) next.delete(group.key)
                      else next.add(group.key)
                      return next
                    })}
                  >
                    {expanded ? 'Hide the list' : `Show all ${group.events.length}`}
                    <ChevronDown size={15} aria-hidden="true" className={expanded ? 'flip' : ''} />
                  </button>
                  {expanded && (
                    <ul className="timeline__sub">
                      {group.events.map((event) => {
                        const view = eventView(event, labels)
                        return (
                          <li key={event.id ?? event.timestamp}>
                            <span>{view.title.replace(/^Blocked /, '')}</span>
                            <span className="timeline__subnote">{view.detail}</span>
                            <time dateTime={event.timestamp}>{clockTime(event.timestamp)}</time>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
                <time className="timeline__time" dateTime={first.timestamp} title={timeAgo(first.timestamp, now)}>
                  {clockTime(first.timestamp)}
                </time>
              </div>
            </li>
          )
        }

        const view = eventView(first, labels)
        const url = first.type === 'screenshot' ? (first.data.url as string | undefined) : undefined
        const deviceName = names.get(first.device_id) ?? 'a device'
        return (
          <li key={group.key} className="timeline__item">
            {showHeading && <h3 className="timeline__day">{headings[index]}</h3>}
            <div className="timeline__row">
              <EventIcon icon={view.icon} tone={view.tone} />
              <div className="timeline__text">
                <p className="timeline__title">{view.title}</p>
                <p className="timeline__meta">
                  {showDevice && deviceLabel(first)}
                  {showDevice && view.detail ? ': ' : ''}
                  {view.detail}
                </p>
                {url && (
                  <a className="timeline__thumb" href={routeHref({ view: 'screens' })}>
                    <img src={url} alt={`Screenshot from ${deviceName}`} loading="lazy" />
                  </a>
                )}
              </div>
              <time className="timeline__time" dateTime={first.timestamp} title={timeAgo(first.timestamp, now)}>
                {clockTime(first.timestamp)}
              </time>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
