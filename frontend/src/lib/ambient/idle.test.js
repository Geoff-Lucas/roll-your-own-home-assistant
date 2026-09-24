import { get } from 'svelte/store'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

let idle

// The module keeps its timer at module level, so each test gets a fresh copy.
beforeEach(async () => {
  vi.useFakeTimers()
  vi.resetModules()
  idle = await import('./idle.js')
})

afterEach(() => vi.useRealTimers())

it('goes idle once the timeout passes with no activity', () => {
  idle.configureIdleTimeout(60)

  vi.advanceTimersByTime(59_000)
  expect(get(idle.isIdle)).toBe(false)

  vi.advanceTimersByTime(1_000)
  expect(get(idle.isIdle)).toBe(true)
})

it('waking restarts the countdown', () => {
  idle.configureIdleTimeout(60)
  vi.advanceTimersByTime(60_000)

  idle.wake()
  expect(get(idle.isIdle)).toBe(false)

  vi.advanceTimersByTime(59_000)
  expect(get(idle.isIdle)).toBe(false)
})

it('never goes idle while suspended (someone reading in the Browser tab)', () => {
  idle.configureIdleTimeout(60)
  idle.idleSuspended.set(true)

  vi.advanceTimersByTime(10 * 60_000)
  expect(get(idle.isIdle)).toBe(false)

  idle.idleSuspended.set(false)
  vi.advanceTimersByTime(60_000)
  expect(get(idle.isIdle)).toBe(true)
})
