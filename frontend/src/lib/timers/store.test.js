import { get } from 'svelte/store'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api.js', () => ({
  getTimers: vi.fn(),
  createTimer: vi.fn(),
  timerAction: vi.fn(),
  deleteTimer: vi.fn(),
}))
vi.mock('../ambient/idle.js', () => ({ wake: vi.fn() }))

let store, api, idle

// The store keeps module-level state, so each test gets fresh copies.
beforeEach(async () => {
  vi.useFakeTimers()
  vi.resetModules()
  api = await import('../api.js')
  idle = await import('../ambient/idle.js')
  store = await import('./store.js')
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

const running = (remaining) => ({ id: 1, kind: 'timer', state: 'running', remaining_seconds: remaining })
const ringing = (id) => ({ id, kind: 'timer', state: 'ringing', remaining_seconds: 0 })

async function startWith(items) {
  api.getTimers.mockResolvedValue({ items })
  const stop = store.startTimers()
  await vi.advanceTimersByTimeAsync(0) // let the first poll land
  return stop
}

describe('live countdowns', () => {
  it('count down between polls from the server-sent seconds left', async () => {
    const stop = await startWith([running(10)])

    await vi.advanceTimersByTimeAsync(750) // three ticks, before the next poll

    expect(get(store.timers)[0].remaining_seconds).toBeCloseTo(9.25)
    stop()
  })

  it('never count below zero', async () => {
    const stop = await startWith([running(0.5)])

    await vi.advanceTimersByTimeAsync(750)

    expect(get(store.timers)[0].remaining_seconds).toBe(0)
    stop()
  })

  it('leave paused timers alone', async () => {
    const stop = await startWith([{ ...running(10), state: 'paused' }])

    await vi.advanceTimersByTimeAsync(750)

    expect(get(store.timers)[0].remaining_seconds).toBe(10)
    stop()
  })

  it('count a running stopwatch up', async () => {
    const stop = await startWith([{ id: 2, kind: 'stopwatch', state: 'running', elapsed_seconds: 5 }])

    await vi.advanceTimersByTimeAsync(500)

    expect(get(store.timers)[0].elapsed_seconds).toBeCloseTo(5.5)
    stop()
  })
})

describe('when something goes off', () => {
  it('wakes the screen once per newly ringing item, not on every poll', async () => {
    api.getTimers
      .mockResolvedValueOnce({ items: [ringing(1)] })
      .mockResolvedValueOnce({ items: [ringing(1)] })
      .mockResolvedValueOnce({ items: [ringing(1), ringing(2)] })

    await store.refresh()
    await store.refresh()
    expect(idle.wake).toHaveBeenCalledTimes(1)

    await store.refresh()
    expect(idle.wake).toHaveBeenCalledTimes(2)
    expect(get(store.ringing).map((item) => item.id)).toEqual([1, 2])
  })

  it('shrugs off a failed poll and keeps what it had', async () => {
    api.getTimers.mockResolvedValueOnce({ items: [running(10)] }).mockRejectedValueOnce(new Error('offline'))

    await store.refresh()
    await expect(store.refresh()).resolves.toBeUndefined()

    expect(get(store.timers)).toHaveLength(1)
  })
})

describe('formatting', () => {
  it('shows minutes and seconds, adding hours past an hour', () => {
    expect(store.formatClock(521)).toBe('8:41')
    expect(store.formatClock(3909)).toBe('1:05:09')
  })

  it('rounds countdowns up, so 0:01 shows until it actually goes off', () => {
    expect(store.formatClock(0.2)).toBe('0:01')
    expect(store.formatClock(0.2, { countdown: false })).toBe('0:00')
    expect(store.formatClock(-3)).toBe('0:00')
  })

  it('writes alarm times the way people say them', () => {
    expect(store.formatAlarmTime('07:30')).toBe('7:30 AM')
    expect(store.formatAlarmTime('00:05')).toBe('12:05 AM')
    expect(store.formatAlarmTime('12:00')).toBe('12:00 PM')
    expect(store.formatAlarmTime('23:45')).toBe('11:45 PM')
  })

  it('names unlabelled items by what they are', () => {
    expect(store.itemName({ kind: 'timer', label: 'Pasta' })).toBe('Pasta')
    expect(store.itemName({ kind: 'alarm', alarm_time: '06:15' })).toBe('Alarm 6:15 AM')
    expect(store.itemName({ kind: 'stopwatch' })).toBe('Stopwatch')
    expect(store.itemName({ kind: 'timer' })).toBe('Timer')
  })
})
