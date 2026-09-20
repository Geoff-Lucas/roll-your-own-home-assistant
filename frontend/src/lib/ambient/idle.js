import { get, writable } from 'svelte/store'

export const isIdle = writable(false)

// While true the dashboard never goes idle. The Browser tab sets this: touches
// inside the separate browser window aren't seen by this page, so a person
// reading a recipe there would otherwise be cut off by the photo carousel.
export const idleSuspended = writable(false)

let timeoutMs = 300_000
let timer

function resetTimer() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    if (get(idleSuspended)) resetTimer()
    else isIdle.set(true)
  }, timeoutMs)
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
