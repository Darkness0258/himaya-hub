import { sameSet } from './domain'
import type { Rules, RulesPatch } from './types'

/** What the form edits. Kept separate from `Rules` so we can tell exactly what changed. */
export interface RulesDraft {
  categories: string[]
  blocked: string[]
  allowed: string[]
  bedtime: boolean
  start: string
  end: string
  interval: number
}

export const INTERVAL_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: 'Off' },
  { value: 120, label: '2 min' },
  { value: 300, label: '5 min' },
  { value: 600, label: '10 min' },
  { value: 1800, label: '30 min' },
]

/** Include the current value even if it is not one of the presets (set through the API). */
export function intervalOptions(current: number): { value: number; label: string }[] {
  if (INTERVAL_OPTIONS.some((o) => o.value === current)) return INTERVAL_OPTIONS
  return [...INTERVAL_OPTIONS, { value: current, label: `${Math.round(current / 60)} min` }].sort((a, b) => a.value - b.value)
}

export function toDraft(rules: Rules): RulesDraft {
  return {
    categories: [...rules.blocked_categories],
    blocked: [...rules.blocked_domains],
    allowed: [...rules.allowed_domains],
    bedtime: rules.bedtime_enabled,
    start: rules.bedtime_start,
    end: rules.bedtime_end,
    interval: rules.snapshot_interval_s,
  }
}

/** Only the fields the parent actually changed (the hub merges partial updates). */
export function diffRules(rules: Rules, draft: RulesDraft): RulesPatch {
  const patch: RulesPatch = {}
  if (!sameSet(rules.blocked_categories, draft.categories)) patch.blocked_categories = draft.categories
  if (!sameSet(rules.blocked_domains, draft.blocked)) patch.blocked_domains = draft.blocked
  if (!sameSet(rules.allowed_domains, draft.allowed)) patch.allowed_domains = draft.allowed
  if (rules.bedtime_enabled !== draft.bedtime) patch.bedtime_enabled = draft.bedtime
  if (rules.bedtime_start !== draft.start) patch.bedtime_start = draft.start
  if (rules.bedtime_end !== draft.end) patch.bedtime_end = draft.end
  if (rules.snapshot_interval_s !== draft.interval) patch.snapshot_interval_s = draft.interval
  return patch
}
