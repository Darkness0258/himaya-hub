import { describe, expect, it } from 'vitest'
import { diffRules, intervalOptions, toDraft } from './rules'
import type { Rules } from './types'

const rules: Rules = {
  device_id: 'windows-aaaa1111', blocked_categories: ['adult', 'gambling'], blocked_domains: ['tiktok.com'], allowed_domains: [],
  bedtime_enabled: false, bedtime_start: '21:00', bedtime_end: '07:00', snapshot_interval_s: 300, updated_at: null,
  bedtime_active: false, paused: false, locked: false, effective_blocked_domains: [],
}

describe('rules draft', () => {
  it('has no changes right after loading', () => {
    expect(diffRules(rules, toDraft(rules))).toEqual({})
  })
  it('sends only what changed', () => {
    const draft = { ...toDraft(rules), bedtime: true, start: '20:30' }
    expect(diffRules(rules, draft)).toEqual({ bedtime_enabled: true, bedtime_start: '20:30' })
  })
  it('ignores re-ordering of lists', () => {
    expect(diffRules(rules, { ...toDraft(rules), categories: ['gambling', 'adult'] })).toEqual({})
  })
  it('detects added and removed sites', () => {
    expect(diffRules(rules, { ...toDraft(rules), blocked: [], allowed: ['example.com'] })).toEqual({ blocked_domains: [], allowed_domains: ['example.com'] })
  })
  it('keeps a custom interval selectable', () => {
    expect(intervalOptions(300).map((o) => o.value)).toEqual([0, 120, 300, 600, 1800])
    expect(intervalOptions(900).map((o) => o.value)).toEqual([0, 120, 300, 600, 900, 1800])
  })
})
