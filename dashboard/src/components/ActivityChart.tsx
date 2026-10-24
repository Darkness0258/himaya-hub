import { BarController, BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip } from 'chart.js'
import { useEffect, useMemo, useRef } from 'react'
import { describeChart, hourLabel } from '../lib/chart'
import type { HistogramBucket } from '../lib/types'

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend)

const cssVar = (name: string): string => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
export function ActivityChart({ buckets, themeKey }: { buckets: HistogramBucket[]; themeKey: string }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const chart = useRef<Chart | null>(null)
  const summary = useMemo(() => describeChart(buckets), [buckets])

  useEffect(() => {
    if (!canvas.current) return
    chart.current?.destroy()
    const text = cssVar('--text-2')
    const grid = cssVar('--line')
    chart.current = new Chart(canvas.current, {
      type: 'bar',
      data: {
        labels: buckets.map((b) => hourLabel(b.t)),
        datasets: [
          { label: 'Blocked sites', data: buckets.map((b) => b.dns_block), backgroundColor: cssVar('--brand'), borderRadius: 3, stack: 'a' },
          { label: 'Alerts', data: buckets.map((b) => b.alerts), backgroundColor: cssVar('--bad'), borderRadius: 3, stack: 'a' },
          { label: 'Screenshots', data: buckets.map((b) => b.screenshots), backgroundColor: cssVar('--gold'), borderRadius: 3, stack: 'a' },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 400 },
        plugins: {
          legend: { position: 'bottom', labels: { color: text, boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 12 } } },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: text, maxTicksLimit: 8, font: { size: 11 } } },
          y: { stacked: true, beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: { color: text, precision: 0, maxTicksLimit: 4, font: { size: 11 } } },
        },
      },
    })
    return () => chart.current?.destroy()
  }, [buckets, themeKey])

  return (
    <div className="chart">
      <canvas ref={canvas} role="img" aria-label={summary} />
    </div>
  )
}
