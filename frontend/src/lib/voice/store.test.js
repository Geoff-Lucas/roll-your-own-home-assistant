import { get } from 'svelte/store'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api.js', () => ({
  getVoiceState: vi.fn(),
  startVoice: vi.fn(),
  stopVoice: vi.fn(() => Promise.resolve()),
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

const snapshot = (state, extra = {}) => ({ state, transcript: null, reply: null, understood: null, error: null, level: 0, ...extra })

describe('tap to talk', () => {
  it('opens, follows the interaction to its answer, then gets out of the way', async () => {
    api.startVoice.mockResolvedValue(snapshot('listening'))
    api.getVoiceState
      .mockResolvedValueOnce(snapshot('thinking', { transcript: 'what time is it' }))
      .mockResolvedValue(snapshot('done', { reply: "It's 3 PM." }))

    await store.startListening()
    expect(get(store.voiceOpen)).toBe(true)
    expect(idle.wake).toHaveBeenCalled() // leaves the photo carousel

    await vi.advanceTimersByTimeAsync(500)
    expect(get(store.voice).reply).toBe("It's 3 PM.")

    await vi.advanceTimersByTimeAsync(7000) // long enough to read
    expect(get(store.voiceOpen)).toBe(false)
  })

  it('stops asking the server once the interaction is done', async () => {
    api.startVoice.mockResolvedValue(snapshot('listening'))
    api.getVoiceState.mockResolvedValue(snapshot('done', { reply: 'Okay.' }))

    await store.startListening()
    await vi.advanceTimersByTimeAsync(250)
    const calls = api.getVoiceState.mock.calls.length

    await vi.advanceTimersByTimeAsync(2000)
    expect(api.getVoiceState.mock.calls.length).toBe(calls)
  })

  it('keeps an error on screen until it is dismissed', async () => {
    api.startVoice.mockResolvedValue(snapshot('listening'))
    api.getVoiceState.mockResolvedValue(snapshot('done', { error: "I didn't hear anything." }))

    await store.startListening()
    await vi.advanceTimersByTimeAsync(20000)

    expect(get(store.voiceOpen)).toBe(true)
    expect(get(store.voice).error).toBe("I didn't hear anything.")
  })

  it('shows a failure to start, without polling', async () => {
    api.startVoice.mockRejectedValue(new Error('The microphone is unavailable'))

    await store.startListening()
    await vi.advanceTimersByTimeAsync(1000)

    expect(get(store.voice)).toMatchObject({ state: 'done', error: 'The microphone is unavailable' })
    expect(api.getVoiceState).not.toHaveBeenCalled()
  })

  it('treats a second tap while listening as "keep watching", not an error', async () => {
    api.startVoice.mockRejectedValue(new Error('Already listening'))
    api.getVoiceState.mockResolvedValue(snapshot('listening'))

    await store.startListening()
    await vi.advanceTimersByTimeAsync(250)

    expect(get(store.voice).error).toBeNull()
    expect(api.getVoiceState).toHaveBeenCalled()
  })
})

describe('hands-free ("Hey Jarvis")', () => {
  it('opens the panel when the server starts listening on its own', async () => {
    api.getVoiceState.mockResolvedValue(snapshot('listening'))
    const stop = store.watchVoice()

    await vi.advanceTimersByTimeAsync(700)

    expect(get(store.voiceOpen)).toBe(true)
    expect(idle.wake).toHaveBeenCalled()
    stop()
  })

  it('leaves the panel closed while nothing is happening', async () => {
    api.getVoiceState.mockResolvedValue(snapshot('idle'))
    const stop = store.watchVoice()

    await vi.advanceTimersByTimeAsync(2100)

    expect(get(store.voiceOpen)).toBe(false)
    stop()
  })
})

describe('closing', () => {
  it('stops the recording if it is still listening', async () => {
    store.voice.set(snapshot('listening'))

    store.closeVoice()

    expect(api.stopVoice).toHaveBeenCalled()
    expect(get(store.voiceOpen)).toBe(false)
  })

  it('does not touch the server when the interaction is already done', () => {
    store.voice.set(snapshot('done'))

    store.closeVoice()

    expect(api.stopVoice).not.toHaveBeenCalled()
  })
})
