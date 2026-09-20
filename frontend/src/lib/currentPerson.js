import { writable } from 'svelte/store'

// There's no login/auth on this shared kiosk — favorites and notes are
// per-person (see RecipeFavorite), so the app needs *some* notion of who's
// currently standing in front of it. This is that: a simple "acting as"
// selector in the header, defaulting to the first known household member.
export const currentPerson = writable(null)
