import { describe, expect, it } from 'vitest'
import { describeChart } from './chart'

const bucket = (t: string, dns_block: number, alerts = 0) => ({ t, dns_block, alerts, screenshots: 0, other: 0 })

describe('describeChart (the text read out by screen readers)', () => {
  it('says so when nothing happened', () => {
    expect(describeChart([])).toMatch(/Nothing was blocked/)
    expect(describeChart([bucket('2026-10-15T10:00:00Z', 0)])).toMatch(/Nothing was blocked/)
  })
  it('names the total, the alerts and the busiest hour', () => {
    const text = describeChart([bucket('2026-10-15T10:00:00Z', 2), bucket('2026-10-15T11:00:00Z', 9, 1), bucket('2026-10-15T12:00:00Z', 1)])
    expect(text).toMatch(/12 blocked websites and 1 alerts/)
    expect(text).toMatch(/with 9 blocks/)
  })
})
