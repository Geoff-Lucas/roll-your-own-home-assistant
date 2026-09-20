import { writable } from 'svelte/store'

// Holds the HTMLInputElement/HTMLTextAreaElement currently "claimed" by the
// virtual keyboard (see vkbd.js), or null when nothing is. A plain store
// rather than component state since VirtualKeyboard is mounted once at the
// app root while any number of inputs anywhere in the tree can claim it.
export const activeField = writable(null)
