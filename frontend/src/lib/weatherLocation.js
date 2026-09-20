import { writable } from 'svelte/store'

// Bumped whenever the user picks a different weather location, so the
// weather widget can refetch immediately instead of waiting out its 5-minute
// poll. A counter (not a boolean) so every change is a distinct update.
export const locationVersion = writable(0)
