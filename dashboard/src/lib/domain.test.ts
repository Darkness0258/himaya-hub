import { describe, expect, it } from 'vitest'
import { normalizeDomain, sameSet, splitEntries } from './domain'

describe('normalizeDomain (must agree with the hub)', () => {
  it.each([
    ['TikTok.com', 'tiktok.com'],
    ['https://www.Kick.com/path?q=1', 'kick.com'],
    ['*.example.org', 'example.org'],
    ['user:pw@host.example.com:8080/x', 'host.example.com'],
    ['example.com.', 'example.com'],
    ['not a domain', ''],
    ['', ''],
    ['localhost', ''],
    ['-bad-.com', ''],
    ['a..b.com', ''],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeDomain(input)).toBe(expected)
  })
})

describe('helpers', () => {
  it('splits pasted lists', () => {
    expect(splitEntries('a.com, b.com\nc.com;  d.com')).toEqual(['a.com', 'b.com', 'c.com', 'd.com'])
  })
  it('compares sets regardless of order', () => {
    expect(sameSet(['a', 'b'], ['b', 'a'])).toBe(true)
    expect(sameSet(['a'], ['a', 'b'])).toBe(false)
  })
})
