import { describe, expect, it } from 'vitest'
import { blocksSinceMidnight, capabilityNotes, eventView, groupEvents, groupSummary, needsAttention, summarizeFamily } from './describe'
import { dayHeading, durationLabel, groupPin, plural, timeAgo } from './format'
import { readableError } from './api'
import type { Device, HubEvent, Stats } from './types'

const NOW = Date.parse('2026-10-15T12:00:00Z')
const ago = (ms: number): string => new Date(NOW - ms).toISOString()
const MIN = 60_000
const HOUR = 3_600_000

function device(partial: Partial<Device> = {}): Device {
  return {
    id: 1, device_id: 'windows-aaaa1111', name: "Sarah's PC", platform: 'windows', ip: '192.168.1.5', owner_type: 'child',
    status: 'online', last_seen: ago(MIN), created_at: ago(5 * HOUR), locked: false, paused: false, caps: {}, agent_version: '2.0.0',
    state: 'online', ...partial,
  }
}
function event(type: string, partial: Partial<HubEvent> = {}): HubEvent {
  return { id: 1, device_id: 'windows-aaaa1111', type, data: {}, timestamp: ago(5 * MIN), ...partial }
}

describe('format', () => {
  it('describes time relative to now', () => {
    expect(timeAgo(ago(10_000), NOW)).toBe('just now')
    expect(timeAgo(ago(12 * MIN), NOW)).toBe('12 min ago')
    expect(timeAgo(ago(59.9 * MIN), NOW)).toBe('59 min ago')
    expect(timeAgo(ago(3 * HOUR), NOW)).toBe('3 h ago')
    expect(timeAgo(ago(30 * HOUR), NOW)).toBe('yesterday')
    expect(timeAgo(null, NOW)).toBe('never')
    expect(timeAgo('garbage', NOW)).toBe('never')
  })
  it('never shows the future as negative', () => {
    expect(timeAgo(new Date(NOW + 5 * MIN).toISOString(), NOW)).toBe('just now')
  })
  it('labels days', () => {
    expect(dayHeading(ago(HOUR), NOW)).toBe('Today')
  })
  it('formats small things', () => {
    expect(durationLabel(0)).toBe('off')
    expect(durationLabel(300)).toBe('5 min')
    expect(durationLabel(3600)).toBe('1 hour')
    expect(groupPin('482913')).toBe('482 913')
    expect(plural(1, 'website')).toBe('1 website')
    expect(plural(3, 'website')).toBe('3 websites')
  })
})

describe('api errors', () => {
  it('flattens FastAPI validation errors', () => {
    const body = { detail: [{ loc: ['body', 'blocked_domains'], msg: "Value error, not a valid domain: 'x y'" }] }
    expect(readableError(body, 422)).toBe("blocked domains: not a valid domain: 'x y'")
  })
  it('passes plain details through and has fallbacks', () => {
    expect(readableError({ detail: 'That key is not valid.' }, 401)).toBe('That key is not valid.')
    expect(readableError(null, 429)).toMatch(/Too many attempts/)
    expect(readableError(null, 500)).toMatch(/hub hit a problem/)
  })
})

describe('eventView', () => {
  it('explains a blocked site and its reason', () => {
    const view = eventView(event('dns_block', { data: { host: 'tiktok.com', reason: 'category:social' } }), { social: 'Social media' })
    expect(view).toMatchObject({ icon: 'ban', title: 'Blocked tiktok.com', detail: 'Social media' })
  })
  it('treats VPNs as alerts', () => {
    expect(eventView(event('vpn_attempt', { data: { interface: 'WireGuard' } }))).toMatchObject({ tone: 'bad', detail: 'WireGuard' })
  })
  it('summarises remote actions', () => {
    expect(eventView(event('remote_action', { data: { action: 'push_notification', message: 'Dinner' } }))).toMatchObject({ title: 'Message sent', detail: 'Dinner' })
    expect(eventView(event('remote_action', { data: { action: 'force_close_app', app: 'chrome' } })).title).toBe('Closed chrome')
  })
  it('lists what changed in rules without dumping raw field names', () => {
    const view = eventView(event('policy_sync', { data: { changed: ['bedtime_enabled', 'bedtime_start', 'blocked_domains'] } }))
    expect(view.detail).toBe('Changed: bedtime, blocked sites')
  })
  it('never throws on unknown types', () => {
    expect(eventView(event('something_new')).title).toBe('Something new')
  })
})

describe('needsAttention', () => {
  it('ignores old events and resolved offline alerts', () => {
    const events = [
      event('device_went_dark', { timestamp: ago(2 * HOUR) }),
      event('vpn_attempt', { device_id: 'windows-bbbb2222', timestamp: ago(30 * HOUR) }),
    ]
    expect(needsAttention(events, [device({ status: 'online' })], NOW)).toEqual([])
    expect(needsAttention(events, [device({ status: 'offline' })], NOW)).toHaveLength(1)
  })
  it('deduplicates per device and type, newest first', () => {
    const events = [
      event('vpn_attempt', { id: 1, timestamp: ago(40 * MIN) }),
      event('vpn_attempt', { id: 2, timestamp: ago(10 * MIN) }),
      event('agent_stopped', { id: 3, timestamp: ago(20 * MIN) }),
    ]
    const result = needsAttention(events, [device()], NOW)
    expect(result.map((e) => e.type)).toEqual(['vpn_attempt', 'agent_stopped'])
  })
})

describe('summarizeFamily', () => {
  it('invites the first device', () => {
    expect(summarizeFamily([], [], { now: NOW }).headline).toMatch(/first device/)
  })
  it('puts alerts first, with who and when', () => {
    const result = summarizeFamily([device()], [event('vpn_attempt', { data: { interface: 'WireGuard Tunnel' }, timestamp: ago(12 * MIN) })], { now: NOW })
    expect(result).toEqual({ headline: 'One thing needs a look.', detail: "Sarah's PC started a VPN (WireGuard Tunnel) 12 min ago.", tone: 'bad' })
  })
  it('counts several alerts', () => {
    const events = [event('vpn_attempt'), event('agent_stopped', { device_id: 'android-cccc3333' })]
    const result = summarizeFamily([device(), device({ device_id: 'android-cccc3333', name: 'Tablet' })], events, { now: NOW })
    expect(result.headline).toBe('2 things need a look.')
  })
  it('then offline devices, then paused ones', () => {
    expect(summarizeFamily([device({ status: 'offline', last_seen: ago(30 * MIN) })], [], { now: NOW })).toMatchObject({ headline: "Sarah's PC is offline.", detail: 'Last seen 30 min ago.', tone: 'warn' })
    expect(summarizeFamily([device({ paused: true, state: 'paused' })], [], { now: NOW })).toMatchObject({ headline: "Sarah's PC is paused.", tone: 'info' })
  })
  it('is calm when everything is fine', () => {
    expect(summarizeFamily([device()], [], { now: NOW, blocksToday: 12 })).toEqual({ headline: 'Everything looks good.', detail: 'Your device is online. 12 websites blocked today.', tone: 'ok' })
    expect(summarizeFamily([device(), device({ device_id: 'x-1' })], [], { now: NOW }).detail).toBe('All 2 devices are online.')
  })
})

describe('capabilityNotes', () => {
  it('is honest about Windows limits', () => {
    const notes = capabilityNotes(device({ caps: { pause: 'proxy', hosts_blocking: false } }), 300)
    expect(notes.find((n) => n.label === 'Website blocking')?.status).toBe('partial')
    expect(notes.find((n) => n.label === 'Pause internet')?.status).toBe('partial')
    expect(notes.find((n) => n.label === 'Erase device')?.status).toBe('no')
    expect(notes.find((n) => n.label === 'Screenshots')?.note).toBe('Every 5 min while the PC is unlocked.')
  })
  it('says screenshots are off when the interval is 0', () => {
    expect(capabilityNotes(device(), 0).find((n) => n.label === 'Screenshots')?.status).toBe('no')
  })
  it('explains the Android consent model', () => {
    const notes = capabilityNotes(device({ platform: 'android', caps: { vpn_dns: true } }), 300)
    expect(notes.find((n) => n.label === 'Screenshots')?.note).toMatch(/approve/)
    expect(notes.find((n) => n.label === 'Pause internet and website blocking')?.status).toBe('yes')
  })
})

describe('blocksSinceMidnight', () => {
  const bucket = (t: number, dns: number) => ({ t: new Date(t).toISOString(), dns_block: dns, alerts: 0, screenshots: 0, other: 0 })
  it('counts only hours that overlap today, in local time', () => {
    const midnight = new Date(NOW)
    midnight.setHours(0, 0, 0, 0)
    const stats = { histogram: [bucket(midnight.getTime() - 3 * HOUR, 5), bucket(midnight.getTime() + HOUR, 3), bucket(NOW - HOUR, 2)] } as Stats
    expect(blocksSinceMidnight(stats, NOW)).toBe(5)
    expect(blocksSinceMidnight(null, NOW)).toBe(0)
  })
})

describe('groupEvents', () => {
  const block = (id: number, minsAgo: number, host: string, dev = 'windows-aaaa1111') =>
    event('dns_block', { id, device_id: dev, data: { host }, timestamp: ago(minsAgo * MIN) })

  it('collapses a run of blocks on one device', () => {
    const groups = groupEvents([block(5, 1, 'a.com'), block(4, 5, 'b.com'), block(3, 9, 'a.com'), block(2, 12, 'c.com')])
    expect(groups).toHaveLength(1)
    expect(groups[0].grouped).toBe(true)
    expect(groups[0].events).toHaveLength(4)
    expect(groupSummary(groups[0])).toEqual({ title: 'Blocked 4 websites', detail: 'a.com, b.com, c.com' })
  })
  it('leaves short runs alone', () => {
    expect(groupEvents([block(2, 1, 'a.com'), block(1, 5, 'b.com')]).map((g) => g.grouped)).toEqual([false, false])
  })
  it('never hides an alert inside a run', () => {
    const groups = groupEvents([block(5, 1, 'a.com'), block(4, 2, 'b.com'), block(3, 3, 'c.com'), event('vpn_attempt', { id: 9, timestamp: ago(4 * MIN) }), block(2, 5, 'd.com')])
    expect(groups.map((g) => g.events[0].type)).toEqual(['dns_block', 'vpn_attempt', 'dns_block'])
    expect(groups[1].grouped).toBe(false)
  })
  it('splits by device and by long gaps', () => {
    const byDevice = groupEvents([block(4, 1, 'a.com'), block(3, 2, 'b.com'), block(2, 3, 'c.com', 'android-bbbb2222'), block(1, 4, 'd.com', 'android-bbbb2222')])
    expect(byDevice.every((g) => !g.grouped)).toBe(true)
    const gap = groupEvents([block(4, 1, 'a.com'), block(3, 2, 'b.com'), block(2, 120, 'c.com'), block(1, 125, 'd.com')])
    expect(gap.every((g) => !g.grouped)).toBe(true)
  })
  it('summarises more than three hosts', () => {
    const group = groupEvents([block(5, 1, 'a.com'), block(4, 2, 'b.com'), block(3, 3, 'c.com'), block(2, 4, 'd.com'), block(1, 5, 'e.com')])[0]
    expect(groupSummary(group).detail).toBe('a.com, b.com, c.com and 2 more')
  })
})
