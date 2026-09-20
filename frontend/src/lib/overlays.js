import { derived, writable } from 'svelte/store'

// Full-screen dialogs (e.g. the location picker) register here while open.
// The Browser tab's window is a separate, always-on-top OS window, so it would
// otherwise sit on top of any dialog drawn by this page — it hides itself
// while this count is above zero.
const openCount = writable(0)

export const overlayOpen = derived(openCount, (count) => count > 0)

/** Call when a dialog opens; call the returned function when it closes. */
export function trackOverlay() {
  openCount.update((count) => count + 1)
  return () => openCount.update((count) => Math.max(0, count - 1))
}
