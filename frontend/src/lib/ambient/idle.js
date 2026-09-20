import { writable } from 'svelte/store'

export const isIdle = writable(false)

let timeoutMs = 300_000
let timer

function resetTimer() {
  clearTimeout(timer)
  timer = setTimeout(() => isIdle.set(true), timeoutMs)
}

export function configureIdleTimeout(seconds) {
  timeoutMs = seconds * 1000
  resetTimer()
}

export function wake() {
  isIdle.set(false)
  resetTimer()
}

// Any touch/click/keypress/mouse-move anywhere in the app counts as
// activity and both wakes the dashboard (if idle) and resets the timer.
// Motion-sensor wake (see ambient/AmbientOverlay.svelte, which polls
// /api/ambient/status) calls wake() the same way — same code path either way.
export function startIdleWatcher() {
  resetTimer()
  ;['pointerdown', 'touchstart', 'keydown', 'mousemove'].forEach((event) =>
    window.addEventListener(event, wake, { passive: true }),
  )
}
