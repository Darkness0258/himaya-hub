import { Activity, House, Images, Plus, Settings, Smartphone } from 'lucide-react'
import type { ReactNode } from 'react'
import { needsAttention } from '../lib/describe'
import { routeHref, useRoute } from '../lib/hooks'
import type { View } from '../lib/hooks'
import { useHub } from '../lib/store'
import { StarMark, Wordmark } from './Brand'

const NAV: { view: View; label: string; icon: typeof House }[] = [
  { view: 'home', label: 'Home', icon: House },
  { view: 'devices', label: 'Devices', icon: Smartphone },
  { view: 'activity', label: 'Activity', icon: Activity },
  { view: 'screens', label: 'Screens', icon: Images },
  { view: 'enroll', label: 'Add a device', icon: Plus },
  { view: 'settings', label: 'Settings', icon: Settings },
]

function ConnectionPill() {
  const { conn } = useHub()
  const text = conn === 'live' ? 'Live' : conn === 'connecting' ? 'Connecting' : 'Reconnecting'
  return (
    <span className={`conn conn--${conn}`} role="status">
      <span className="conn__dot" aria-hidden="true" />
      {text}
    </span>
  )
}

export function Shell({ children }: { children: ReactNode }) {
  const route = useRoute()
  const { devices, events } = useHub()
  const alerts = needsAttention(events, devices).length

  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>

      <aside className="rail" aria-label="Main">
        <a className="rail__brand" href={routeHref({ view: 'home' })} aria-label="Himaya home">
          <StarMark size={38} />
          <Wordmark />
        </a>
        <nav className="rail__nav">
          {NAV.map(({ view, label, icon: Icon }) => (
            <a key={view} href={routeHref({ view })} className={`rail__link ${route.view === view ? 'is-current' : ''}`} aria-current={route.view === view ? 'page' : undefined}>
              <Icon size={19} strokeWidth={1.9} aria-hidden="true" />
              <span>{label}</span>
              {view === 'activity' && alerts > 0 && <span className="badge-count" aria-label={`${alerts} alerts`}>{alerts}</span>}
            </a>
          ))}
        </nav>
        <div className="rail__foot">
          <ConnectionPill />
          <p className="rail__host">{window.location.host}</p>
        </div>
      </aside>

      <header className="topbar">
        <a className="topbar__brand" href={routeHref({ view: 'home' })} aria-label="Himaya home">
          <StarMark size={30} />
          <Wordmark />
        </a>
        <ConnectionPill />
        <a className="iconbtn" href={routeHref({ view: 'settings' })} aria-label="Settings">
          <Settings size={19} aria-hidden="true" />
        </a>
      </header>

      <main id="main" className="main" tabIndex={-1}>
        {children}
      </main>

      <nav className="tabbar" aria-label="Main">
        {NAV.filter((item) => item.view !== 'settings').map(({ view, label, icon: Icon }) => (
          <a key={view} href={routeHref({ view })} className={`tabbar__link ${route.view === view ? 'is-current' : ''}`} aria-current={route.view === view ? 'page' : undefined}>
            <Icon size={21} strokeWidth={1.9} aria-hidden="true" />
            <span>{view === 'enroll' ? 'Add' : label}</span>
            {view === 'activity' && alerts > 0 && <span className="badge-dot" aria-label={`${alerts} alerts`} />}
          </a>
        ))}
      </nav>
    </div>
  )
}
