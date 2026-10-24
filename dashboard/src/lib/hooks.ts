import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

/** Re-renders every `intervalMs` so "5 min ago" labels stay fresh. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

export function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', notify)
      return () => list.removeEventListener('change', notify)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false)
}

// ---------------------------------------------------------------------------
// Hash routing: #/home  #/devices  #/devices/<id>/rules  #/activity ...
// ---------------------------------------------------------------------------
export type View = 'home' | 'devices' | 'activity' | 'screens' | 'enroll' | 'settings'
export type DeviceTab = 'rules' | 'screens' | 'activity' | 'details'

export interface Route {
  view: View
  deviceId?: string
  tab: DeviceTab
}

const VIEWS: View[] = ['home', 'devices', 'activity', 'screens', 'enroll', 'settings']
const TABS: DeviceTab[] = ['rules', 'screens', 'activity', 'details']

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const view = (VIEWS as string[]).includes(parts[0]) ? (parts[0] as View) : 'home'
  if (view !== 'devices') return { view, tab: 'rules' }
  const tab = (TABS as string[]).includes(parts[2]) ? (parts[2] as DeviceTab) : 'rules'
  return { view, deviceId: parts[1] ? decodeURIComponent(parts[1]) : undefined, tab }
}

export function routeHref(route: Partial<Route> & { view: View }): string {
  if (route.view === 'devices' && route.deviceId) {
    return `#/devices/${encodeURIComponent(route.deviceId)}${route.tab && route.tab !== 'rules' ? `/${route.tab}` : ''}`
  }
  return `#/${route.view}`
}

export function navigate(route: Partial<Route> & { view: View }): void {
  window.location.hash = routeHref(route)
}

let cachedHash = ''
let cachedRoute: Route = parseHash('')
function currentRoute(): Route {
  const hash = window.location.hash
  if (hash !== cachedHash) {
    cachedHash = hash
    cachedRoute = parseHash(hash)
  }
  return cachedRoute
}

export function useRoute(): Route {
  const subscribe = useCallback((notify: () => void) => {
    window.addEventListener('hashchange', notify)
    return () => window.removeEventListener('hashchange', notify)
  }, [])
  return useSyncExternalStore(subscribe, currentRoute, () => parseHash(''))
}

// ---------------------------------------------------------------------------
// Theme: auto follows the system; light/dark are remembered on this device.
// ---------------------------------------------------------------------------
export type ThemePref = 'auto' | 'light' | 'dark'

export function readThemePref(): ThemePref {
  try {
    const saved = localStorage.getItem('himaya.theme')
    return saved === 'light' || saved === 'dark' ? saved : 'auto'
  } catch {
    return 'auto'
  }
}

export function applyTheme(pref: ThemePref): void {
  const dark = pref === 'auto' ? window.matchMedia('(prefers-color-scheme: dark)').matches : pref === 'dark'
  const root = document.documentElement
  root.setAttribute('data-theme', dark ? 'dark' : 'light')
  root.setAttribute('data-theme-pref', pref)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0b1020' : '#f4f5fb')
  try {
    if (pref === 'auto') localStorage.removeItem('himaya.theme')
    else localStorage.setItem('himaya.theme', pref)
  } catch {
    /* ignore */
  }
}

export function useTheme(): { pref: ThemePref; dark: boolean; setPref: (pref: ThemePref) => void } {
  const [pref, setPrefState] = useState<ThemePref>(readThemePref)
  const systemDark = useMedia('(prefers-color-scheme: dark)')
  useEffect(() => applyTheme(pref), [pref, systemDark])
  return { pref, dark: pref === 'auto' ? systemDark : pref === 'dark', setPref: setPrefState }
}

/** The theme actually showing (light/dark), observed from the <html> element so every component agrees. */
export function useResolvedTheme(): 'light' | 'dark' {
  const subscribe = useCallback((notify: () => void) => {
    const observer = new MutationObserver(notify)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  return useSyncExternalStore(subscribe, () => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'), () => 'dark')
}

export function greeting(now: number = Date.now()): string {
  const hour = new Date(now).getHours()
  if (hour < 5) return 'Good night'
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  if (hour < 22) return 'Good evening'
  return 'Good night'
}
