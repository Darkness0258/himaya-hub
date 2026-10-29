/** Live view helpers. Pure, so they are unit-tested. */
export const LIVE_DEFAULT_S = 60

/** Whole seconds left until `endsAt` (milliseconds since the epoch). Never negative. */
export function secondsLeft(endsAt: number, now: number): number {
  return Math.max(0, Math.ceil((endsAt - now) / 1000))
}

/** The same picture address with a changing number added, so the browser fetches a fresh frame. */
export function frameUrl(base: string, tick: number): string {
  return `${base}${base.includes('?') ? '&' : '?'}t=${tick}`
}

/** "1:05" style countdown. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
