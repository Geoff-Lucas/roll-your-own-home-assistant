import { get, writable } from 'svelte/store'
import { getVoiceState, startVoice, stopVoice } from '../api.js'
import { wake } from '../ambient/idle.js'

const POLL_MS = 250
// After a successful answer, leave it on screen long enough to read, then get
// out of the way. Errors stay until dismissed — they need reading and acting on.
const AUTO_CLOSE_MS = 7000

const IDLE = { state: 'idle', transcript: null, reply: null, understood: null, error: null, level: 0 }

/** The server's view of the current interaction. */
export const voice = writable(IDLE)
/** Whether the listening panel is showing. */
export const voiceOpen = writable(false)

let pollTimer
let closeTimer

function stopPolling() {
  clearInterval(pollTimer)
  pollTimer = undefined
}

async function poll() {
  try {
    const snapshot = await getVoiceState()
    voice.set(snapshot)
    if (snapshot.state === 'done' || snapshot.state === 'idle') {
      stopPolling()
      if (snapshot.state === 'done' && !snapshot.error) {
        clearTimeout(closeTimer)
        closeTimer = setTimeout(closeVoice, AUTO_CLOSE_MS)
      }
    }
  } catch {
    // A missed poll isn't worth surfacing; the next one catches up.
  }
}

const WATCH_MS = 700
const BUSY = ['listening', 'transcribing', 'thinking', 'speaking']
let watchTimer

/**
 * Keep an eye out for an interaction that started without a tap — i.e. after
 * "Hey Jarvis" — and bring the panel up for it. Cheap: one small local request
 * every 0.7s while the panel is closed.
 */
export function watchVoice() {
  clearInterval(watchTimer)
  watchTimer = setInterval(async () => {
    if (get(voiceOpen)) return
    try {
      const snapshot = await getVoiceState()
      if (BUSY.includes(snapshot.state)) {
        clearTimeout(closeTimer)
        voice.set(snapshot)
        voiceOpen.set(true)
        wake() // leave the photo carousel
        stopPolling()
        pollTimer = setInterval(poll, POLL_MS)
      }
    } catch {
      // Backend briefly unavailable (e.g. restarting): try again next time.
    }
  }, WATCH_MS)
  return () => clearInterval(watchTimer)
}

export async function startListening() {
  clearTimeout(closeTimer)
  voiceOpen.set(true)
  wake() // leave the photo carousel
  voice.set({ ...IDLE, state: 'listening' })
  try {
    voice.set(await startVoice())
  } catch (err) {
    // 409 means it is already listening (e.g. a second tap): just keep watching it.
    if (!String(err.message).includes('Already')) {
      voice.set({ ...IDLE, state: 'done', error: err.message })
      return
    }
  }
  stopPolling()
  pollTimer = setInterval(poll, POLL_MS)
}

/** "Done talking": the server finishes the recording and carries on. */
export function finishListening() {
  stopVoice().catch(() => {})
}

export function closeVoice() {
  clearTimeout(closeTimer)
  stopPolling()
  // Only ever close a finished interaction; while it is busy the panel stays.
  if (get(voice).state === 'listening') stopVoice().catch(() => {})
  voiceOpen.set(false)
}
