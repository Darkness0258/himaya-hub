const MIN = 60_000
const HOUR = 3_600_000
const DAY = 86_400_000

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

/** "just now", "12 min ago", "3 h ago", "yesterday", "12 Oct". */
export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  const t = parseTime(iso)
  if (t === null) return 'never'
  const diff = Math.max(0, now - t)
  if (diff < 45_000) return 'just now'
  if (diff < HOUR) return `${Math.max(1, Math.floor(diff / MIN))} min ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)} h ago`
  if (diff < 2 * DAY) return 'yesterday'
  return new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

export function clockTime(iso: string | null | undefined): string {
  const t = parseTime(iso)
  return t === null ? '' : new Date(t).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function dateTime(iso: string | null | undefined): string {
  const t = parseTime(iso)
  if (t === null) return ''
  const d = new Date(t)
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}, ${clockTime(iso)}`
}

const startOfDay = (t: number): number => {
  const d = new Date(t)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/** Group heading for a timeline: Today, Yesterday, or "Mon 12 Oct". */
export function dayHeading(iso: string, now: number = Date.now()): string {
  const t = parseTime(iso)
  if (t === null) return ''
  const days = Math.round((startOfDay(now) - startOfDay(t)) / DAY)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return new Date(t).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}

export function durationLabel(seconds: number): string {
  if (seconds <= 0) return 'off'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const hours = seconds / 3600
  return hours === 1 ? '1 hour' : `${hours} hours`
}

/** "482913" -> "482 913" for easy reading aloud. */
export function groupPin(pin: string): string {
  return pin.length === 6 ? `${pin.slice(0, 3)} ${pin.slice(3)}` : pin
}

export function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}
