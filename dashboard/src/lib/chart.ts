import type { HistogramBucket } from './types'

export const hourLabel = (iso: string): string => new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric' }).replace(/\s/g, '').toLowerCase()

export function describeChart(buckets: HistogramBucket[]): string {
  const total = buckets.reduce((sum, b) => sum + b.dns_block, 0)
  if (buckets.length === 0 || (total === 0 && buckets.every((b) => b.alerts === 0))) return 'Nothing was blocked and there were no alerts in the last 24 hours.'
  const peak = buckets.reduce((best, b) => (b.dns_block > best.dns_block ? b : best), buckets[0])
  const alerts = buckets.reduce((sum, b) => sum + b.alerts, 0)
  return `${total} blocked websites and ${alerts} alerts in the last 24 hours. Busiest hour: ${hourLabel(peak.t)} with ${peak.dns_block} blocks.`
}
