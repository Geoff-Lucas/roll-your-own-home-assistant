import { activeField } from './activeField.js'

/**
 * Svelte action that opts a text input/textarea into the in-app virtual
 * keyboard instead of the OS/browser's own on-screen keyboard.
 *
 * `inputmode="none"` is the key trick: the element stays genuinely
 * focusable (real caret, selection, native undo all keep working), it just
 * tells Chromium not to pop up its own on-screen keyboard for it — ours
 * fills that role instead. This is what PLAN.md's "Touch input / on-screen
 * keyboard" section calls for: avoid the OS input method entirely rather
 * than fight its quirks under kiosk Chromium.
 *
 * Usage: <input type="text" bind:value={x} use:vkbd />
 */
export function vkbd(node) {
  node.setAttribute('inputmode', 'none')

  function handleFocus() {
    activeField.set(node)
  }

  function handleBlur() {
    // A tap on the virtual keyboard itself never reaches here — see
    // VirtualKeyboard's mousedown/touchstart handler, which prevents the
    // browser from blurring the real input in the first place. So a blur
    // here always means focus genuinely moved elsewhere.
    activeField.update((current) => (current === node ? null : current))
  }

  node.addEventListener('focus', handleFocus)
  node.addEventListener('blur', handleBlur)

  return {
    destroy() {
      node.removeEventListener('focus', handleFocus)
      node.removeEventListener('blur', handleBlur)
      activeField.update((current) => (current === node ? null : current))
    },
  }
}
