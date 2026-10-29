import { describe, expect, it } from 'vitest'
import { clock, frameUrl, secondsLeft } from './live'

describe('live view helpers', () => {
  it('counts whole seconds down and never goes below zero', () => {
    expect(secondsLeft(10_000, 0)).toBe(10)
    expect(secondsLeft(10_000, 9_001)).toBe(1)
    expect(secondsLeft(10_000, 10_000)).toBe(0)
    expect(secondsLeft(10_000, 99_000)).toBe(0)
  })

  it('adds a cache-busting number to the signed address', () => {
    expect(frameUrl('/live/abc?exp=1&sig=2', 7)).toBe('/live/abc?exp=1&sig=2&t=7')
    expect(frameUrl('/live/abc', 3)).toBe('/live/abc?t=3')
  })

  it('formats the countdown', () => {
    expect(clock(65)).toBe('1:05')
    expect(clock(9)).toBe('0:09')
    expect(clock(-4)).toBe('0:00')
  })
})
