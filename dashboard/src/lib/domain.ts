// Mirrors hub/filtering.py normalize_domain so the form accepts exactly what the hub accepts.
const DOMAIN_RE = /^(?=.{1,253}$)(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$/

export function normalizeDomain(value: string): string {
  let v = value.trim().toLowerCase()
  if (!v) return ''
  const scheme = v.indexOf('://')
  if (scheme !== -1) v = v.slice(scheme + 3)
  v = v.split(/[/?#]/, 1)[0]
  v = v.slice(v.lastIndexOf('@') + 1)
  v = v.split(':', 1)[0]
  v = v.replace(/\.+$/, '')
  if (v.startsWith('*.')) v = v.slice(2)
  if (v.startsWith('www.')) v = v.slice(4)
  return DOMAIN_RE.test(v) ? v : ''
}

/** Split pasted text ("a.com, b.com\nc.com") into candidate entries. */
export function splitEntries(text: string): string[] {
  return text.split(/[\s,;]+/).map((part) => part.trim()).filter(Boolean)
}

export function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every((item) => set.has(item))
}
