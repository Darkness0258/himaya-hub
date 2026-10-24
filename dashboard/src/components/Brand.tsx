/** Eight-point star polygon points (the project's mark: a khatam, a symbol of protection and home). */
function starPoints(cx: number, cy: number, outer: number, inner: number, points = 8): string {
  const out: string[] = []
  for (let i = 0; i < points * 2; i++) {
    const radius = i % 2 === 0 ? outer : inner
    const angle = (Math.PI / points) * i - Math.PI / 2
    out.push(`${(cx + radius * Math.cos(angle)).toFixed(2)},${(cy + radius * Math.sin(angle)).toFixed(2)}`)
  }
  return out.join(' ')
}

const STAR = starPoints(32, 32, 21, 11.2)

export function StarMark({ size = 36, tile = true }: { size?: number; tile?: boolean }) {
  return (
    <svg className="starmark" width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      {tile && <rect width="64" height="64" rx="16" fill="var(--mark-tile)" />}
      <polygon points={STAR} fill="var(--mark-star)" />
      <circle cx="32" cy="32" r="5.2" fill="var(--mark-core)" />
    </svg>
  )
}

export function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wordmark__latin">Himaya</span>
      <span className="wordmark__arabic" lang="ar" aria-hidden="true">
        حماية
      </span>
    </span>
  )
}

/** Tessellated stars used behind the hero and the sign-in screen. Decorative only. */
export function StarPattern() {
  return (
    <svg className="starpattern" aria-hidden="true" focusable="false" width="100%" height="100%">
      <defs>
        <pattern id="khatam" width="72" height="72" patternUnits="userSpaceOnUse">
          <polygon points={starPoints(36, 36, 24, 13)} fill="none" stroke="currentColor" strokeWidth="1" />
          <polygon points={starPoints(0, 0, 24, 13)} fill="none" stroke="currentColor" strokeWidth="1" />
          <polygon points={starPoints(72, 0, 24, 13)} fill="none" stroke="currentColor" strokeWidth="1" />
          <polygon points={starPoints(0, 72, 24, 13)} fill="none" stroke="currentColor" strokeWidth="1" />
          <polygon points={starPoints(72, 72, 24, 13)} fill="none" stroke="currentColor" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#khatam)" />
    </svg>
  )
}
