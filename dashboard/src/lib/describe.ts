import { clockTime, plural, timeAgo } from './format'
import type { Device, HubEvent, Platform, Stats } from './types'

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral'
export type IconKey =
  | 'ban'
  | 'vpn'
  | 'offline'
  | 'online'
  | 'lock'
  | 'unlock'
  | 'pause'
  | 'play'
  | 'message'
  | 'camera'
  | 'rules'
  | 'plus'
  | 'alert'
  | 'close'
  | 'erase'
  | 'info'

export interface EventView {
  icon: IconKey
  tone: Tone
  title: string
  detail?: string
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')

export const PLATFORM_LABEL: Record<Platform, string> = {
  android: 'Android',
  windows: 'Windows PC',
  ios: 'iPhone or iPad',
  macos: 'Mac',
  linux: 'Linux PC',
}

export function categoryLabel(name: string, labels: Record<string, string> = {}): string {
  return labels[name] ?? name.replace(/[_-]/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

function describeReason(reason: string, labels: Record<string, string>): string | undefined {
  if (!reason) return undefined
  if (reason.startsWith('category:')) return categoryLabel(reason.slice('category:'.length), labels)
  if (reason === 'custom') return 'On your block list'
  if (reason === 'bedtime') return 'Bedtime'
  if (reason === 'paused') return 'Internet paused'
  return undefined
}

const CHANGED_LABEL: Record<string, string> = {
  blocked_categories: 'categories',
  blocked_domains: 'blocked sites',
  allowed_domains: 'allowed sites',
  bedtime_enabled: 'bedtime',
  bedtime_start: 'bedtime',
  bedtime_end: 'bedtime',
  snapshot_interval_s: 'screenshots',
}

export function changedSummary(keys: unknown): string {
  if (!Array.isArray(keys)) return ''
  const names = [...new Set(keys.map((k) => CHANGED_LABEL[String(k)] ?? String(k)))]
  return names.join(', ')
}

/** One event -> an icon, a tone and plain-language text. Pure, so it is unit-tested. */
export function eventView(event: HubEvent, labels: Record<string, string> = {}): EventView {
  const d = event.data ?? {}
  switch (event.type) {
    case 'dns_block':
      return { icon: 'ban', tone: 'neutral', title: `Blocked ${text(d.host) || 'a website'}`, detail: describeReason(text(d.reason), labels) }
    case 'vpn_attempt':
      return { icon: 'vpn', tone: 'bad', title: 'A VPN was started', detail: text(d.interface) || undefined }
    case 'device_went_dark':
      return { icon: 'offline', tone: 'warn', title: 'Went offline', detail: 'The device stopped checking in.' }
    case 'device_online':
      return { icon: 'online', tone: 'ok', title: 'Back online' }
    case 'device_locked':
      return { icon: 'lock', tone: 'info', title: 'Screen locked' }
    case 'device_unlocked':
      return { icon: 'unlock', tone: 'info', title: 'Screen unlocked' }
    case 'screenshot':
      return { icon: 'camera', tone: 'neutral', title: 'Screenshot captured' }
    case 'live_started':
      return { icon: 'camera', tone: 'info', title: 'Live view started', detail: typeof d.duration_s === 'number' ? `Up to ${d.duration_s} seconds` : undefined }
    case 'live_ended':
      return { icon: 'camera', tone: 'neutral', title: 'Live view ended', detail: text(d.reason) ? text(d.reason).replace(/^./, (c) => c.toUpperCase()) : undefined }
    case 'policy_sync': {
      const changed = changedSummary(d.changed)
      return { icon: 'rules', tone: 'neutral', title: 'Rules updated', detail: changed ? `Changed: ${changed}` : undefined }
    }
    case 'device_paired':
      return { icon: 'plus', tone: 'ok', title: 'Added to Himaya', detail: text(d.name) || undefined }
    case 'agent_stopped':
      return { icon: 'alert', tone: 'bad', title: 'Himaya was stopped on this device', detail: text(d.reason) || undefined }
    case 'enforcement_notice':
      // A parent hardening the install is good news, not a problem.
      if (d.kind === 'hardened') return { icon: 'lock', tone: 'ok', title: 'Himaya was hardened on this PC', detail: text(d.message) || undefined }
      return { icon: 'alert', tone: 'warn', title: "Himaya can't enforce a rule here", detail: text(d.message) || undefined }
    case 'remote_action':
      switch (text(d.action)) {
        case 'pause':
        case 'block_internet':
          return { icon: 'pause', tone: 'info', title: 'Internet paused' }
        case 'unpause':
        case 'unblock_internet':
          return { icon: 'play', tone: 'info', title: 'Internet resumed' }
        case 'push_notification':
          return { icon: 'message', tone: 'info', title: 'Message sent', detail: text(d.message) || undefined }
        case 'force_close_app':
          return { icon: 'close', tone: 'info', title: `Closed ${text(d.app) || 'an app'}` }
        case 'snapshot':
          return { icon: 'camera', tone: 'info', title: 'Screenshot requested' }
        case 'wipe':
          return { icon: 'erase', tone: 'bad', title: 'Erase requested' }
        default:
          return { icon: 'info', tone: 'info', title: 'Command sent' }
      }
    default:
      return { icon: 'info', tone: 'neutral', title: event.type.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) }
  }
}

const ATTENTION_TYPES = new Set(['vpn_attempt', 'agent_stopped', 'enforcement_notice', 'device_went_dark'])

/** Recent events a parent should look at. A "went offline" alert resolves itself once the device is back. */
export function needsAttention(events: HubEvent[], devices: Device[], now: number = Date.now(), windowMs = 24 * 3_600_000): HubEvent[] {
  const byId = new Map(devices.map((d) => [d.device_id, d]))
  const seen = new Set<string>()
  const out: HubEvent[] = []
  // Newest first, whatever order the caller used, so deduplication keeps the latest of each kind.
  const newestFirst = [...events].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
  for (const event of newestFirst) {
    if (!ATTENTION_TYPES.has(event.type)) continue
    if (event.type === 'enforcement_notice' && event.data?.kind === 'hardened') continue
    const stamp = Date.parse(event.timestamp)
    if (Number.isNaN(stamp) || now - stamp > windowMs) continue
    if (event.type === 'device_went_dark' && byId.get(event.device_id)?.status === 'online') continue
    const key = `${event.device_id}:${event.type}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(event)
  }
  return out
}

function attentionSentence(event: HubEvent, name: string, now: number): string {
  const when = timeAgo(event.timestamp, now)
  switch (event.type) {
    case 'vpn_attempt': {
      const iface = text(event.data.interface)
      return `${name} started a VPN${iface ? ` (${iface})` : ''} ${when}.`
    }
    case 'device_went_dark':
      return `${name} went offline ${when}.`
    case 'agent_stopped':
      return `Himaya was stopped on ${name} ${when}.`
    default:
      return `${name} reported a problem ${when}.`
  }
}

export interface FamilySummary {
  headline: string
  detail: string
  tone: Tone
}

/** The sentence at the top of Home: answers "is everything OK?" before anything else. */
export function summarizeFamily(devices: Device[], events: HubEvent[], opts: { now?: number; blocksToday?: number } = {}): FamilySummary {
  const now = opts.now ?? Date.now()
  const blocks = opts.blocksToday ?? 0
  if (devices.length === 0) {
    return { headline: "Let's protect your first device.", detail: 'Add a Windows PC or an Android phone. It takes about two minutes.', tone: 'neutral' }
  }
  const names = new Map(devices.map((d) => [d.device_id, d.name]))
  const alerts = needsAttention(events, devices, now)
  if (alerts.length > 0) {
    const newest = alerts[0]
    return {
      headline: alerts.length === 1 ? 'One thing needs a look.' : `${alerts.length} things need a look.`,
      detail: attentionSentence(newest, names.get(newest.device_id) ?? 'A device', now),
      tone: 'bad',
    }
  }
  const offline = devices.filter((d) => d.status === 'offline')
  if (offline.length > 0) {
    const first = offline[0]
    return {
      headline: offline.length === 1 ? `${first.name} is offline.` : `${offline.length} devices are offline.`,
      detail: offline.length === 1 ? `Last seen ${timeAgo(first.last_seen, now)}.` : offline.map((d) => d.name).join(', ') + '.',
      tone: 'warn',
    }
  }
  const restricted = devices.filter((d) => d.locked || d.paused)
  if (restricted.length > 0) {
    const first = restricted[0]
    const what = first.locked ? 'locked' : 'paused'
    return {
      headline: restricted.length === 1 ? `${first.name} is ${what}.` : `${restricted.length} devices are locked or paused.`,
      detail: 'You can resume them from the Devices page.',
      tone: 'info',
    }
  }
  const online = `${devices.length === 1 ? 'Your device is' : `All ${devices.length} devices are`} online.`
  return {
    headline: 'Everything looks good.',
    detail: blocks > 0 ? `${online} ${plural(blocks, 'website')} blocked today.` : online,
    tone: 'ok',
  }
}

export interface CapabilityNote {
  label: string
  status: 'yes' | 'partial' | 'no'
  note: string
}

/** Honest list of what Himaya can and cannot enforce on a specific device. */
export function capabilityNotes(device: Device, snapshotIntervalS?: number): CapabilityNote[] {
  const caps = device.caps ?? {}
  const shots =
    snapshotIntervalS === 0
      ? ({ label: 'Screenshots', status: 'no', note: 'Turned off in Rules.' } as const)
      : device.platform === 'android'
        ? ({ label: 'Screenshots', status: 'partial', note: 'On request only. The child must approve each one on the phone.' } as const)
        : ({ label: 'Screenshots', status: 'yes', note: snapshotIntervalS ? `Every ${Math.round(snapshotIntervalS / 60)} min while the PC is unlocked.` : 'Scheduled and on request.' } as const)

  if (device.platform === 'windows') {
    return [
      { label: 'Lock screen', status: 'yes', note: 'Re-locks every few seconds while locked, so signing back in does not help.' },
      caps.pause === 'proxy'
        ? { label: 'Pause internet', status: 'partial', note: 'Works for browsers and most apps (it uses the Windows proxy setting). A hub DNS setup is stricter.' }
        : { label: 'Pause internet', status: 'no', note: 'This agent has not reported how it pauses yet.' },
      caps.hosts_blocking
        ? { label: 'Website blocking', status: 'yes', note: "Written to the PC's hosts file." }
        : { label: 'Website blocking', status: 'partial', note: 'Needs Administrator rights on the PC, or point its DNS at the hub.' },
      shots,
      caps.live_view
        ? { label: 'Live view', status: 'yes', note: 'Up to two minutes at a time. The child sees a notice and the tray icon changes. Nothing is saved.' }
        : { label: 'Live view', status: 'no', note: 'Update the Himaya agent on this PC to use it.' },
      { label: 'VPN alerts', status: 'yes', note: 'You are told when a VPN adapter comes up.' },
      { label: 'Erase device', status: 'no', note: 'Not available on Windows.' },
    ]
  }
  if (device.platform === 'android') {
    return [
      caps.lock === false
        ? { label: 'Lock screen', status: 'no', note: 'Turn on Device admin in the Himaya app.' }
        : { label: 'Lock screen', status: 'yes', note: 'Uses Android device admin.' },
      caps.vpn_dns
        ? { label: 'Pause internet and website blocking', status: 'yes', note: "Through the hub's DNS filter (the Himaya VPN is on)." }
        : { label: 'Pause internet and website blocking', status: 'partial', note: "Turn on 'Filter websites' in the Himaya app so lookups go through the hub." },
      shots,
      { label: 'VPN alerts', status: 'yes', note: 'You are told when another VPN is turned on.' },
      caps.wipe === false
        ? { label: 'Erase device', status: 'no', note: 'Needs Device admin.' }
        : { label: 'Erase device', status: 'yes', note: 'For lost or stolen phones. Always asks you to confirm.' },
    ]
  }
  return [{ label: 'Remote actions', status: 'partial', note: 'This kind of device has limited support.' }]
}

export function lastSeenText(device: Device, now: number = Date.now()): string {
  if (device.status === 'online') return 'Online now'
  return device.last_seen ? `Last seen ${timeAgo(device.last_seen, now)}` : 'Not seen yet'
}

export function stateLabel(state: Device['state']): string {
  return { online: 'Online', offline: 'Offline', locked: 'Locked', paused: 'Paused' }[state]
}

export { clockTime }

function startOfLocalDay(now: number): number {
  const d = new Date(now)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/** Blocked lookups since local midnight (the histogram is hourly UTC buckets). */
export function blocksSinceMidnight(stats: Stats | null, now: number): number {
  if (!stats) return 0
  const start = startOfLocalDay(now)
  return stats.histogram.filter((b) => Date.parse(b.t) + 3_600_000 > start).reduce((sum, b) => sum + b.dns_block, 0)
}


export interface EventGroup {
  key: string
  /** Newest first. One event for a normal row, several for a collapsed run of blocked sites. */
  events: HubEvent[]
  grouped: boolean
}

/**
 * Collapse runs of blocked-site events on one device (each less than `gapMs` after the previous) so a
 * busy afternoon does not bury a VPN alert. Anything that is not a block breaks the run.
 */
export function groupEvents(events: HubEvent[], opts: { gapMs?: number; minRun?: number } = {}): EventGroup[] {
  const gapMs = opts.gapMs ?? 30 * 60_000
  const minRun = opts.minRun ?? 3
  const keyOf = (e: HubEvent): string => `${e.id ?? `${e.timestamp}:${e.type}:${e.device_id}`}`
  const groups: EventGroup[] = []
  let run: HubEvent[] = []

  const flush = () => {
    if (run.length >= minRun) groups.push({ key: `g${keyOf(run[0])}`, events: run, grouped: true })
    else for (const e of run) groups.push({ key: keyOf(e), events: [e], grouped: false })
    run = []
  }

  for (const event of events) {
    if (event.type !== 'dns_block') {
      flush()
      groups.push({ key: keyOf(event), events: [event], grouped: false })
      continue
    }
    const last = run[run.length - 1]
    if (last && (last.device_id !== event.device_id || Math.abs(Date.parse(last.timestamp) - Date.parse(event.timestamp)) > gapMs)) flush()
    run.push(event)
  }
  flush()
  return groups
}

/** Text for a collapsed run: "Blocked 5 websites" and the first few names. */
export function groupSummary(group: EventGroup): { title: string; detail: string } {
  const hosts: string[] = []
  for (const event of group.events) {
    const host = text(event.data.host)
    if (host && !hosts.includes(host)) hosts.push(host)
  }
  const shown = hosts.slice(0, 3).join(', ')
  const more = hosts.length - 3
  return {
    title: `Blocked ${group.events.length} websites`,
    detail: more > 0 ? `${shown} and ${more} more` : shown,
  }
}
