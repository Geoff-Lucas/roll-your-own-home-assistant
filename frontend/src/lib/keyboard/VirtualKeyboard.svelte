<script>
  import { onDestroy, onMount } from 'svelte'
  import * as SimpleKeyboardModule from 'simple-keyboard'
  import 'simple-keyboard/build/css/index.css'
  import { activeField } from './activeField.js'

  // simple-keyboard's CJS/ESM interop is quirky under Vite — a plain
  // `import Keyboard from 'simple-keyboard'` resolves to a namespace
  // wrapper rather than the class itself here, so unwrap defensively
  // instead of assuming one specific shape.
  const Keyboard = SimpleKeyboardModule.default?.default ?? SimpleKeyboardModule.default ?? SimpleKeyboardModule

  let keyboardEl
  let keyboard
  let shiftLayout = $state(false)

  const visible = $derived($activeField !== null)

  function dispatchInputEvent(node) {
    node.dispatchEvent(new Event('input', { bubbles: true }))
  }

  function onKeyboardChange(value) {
    const node = $activeField
    if (!node) return
    node.value = value
    dispatchInputEvent(node)
  }

  function onKeyPress(button) {
    if (button === '{shift}') {
      shiftLayout = !shiftLayout
      keyboard.setOptions({ layoutName: shiftLayout ? 'shift' : 'default' })
    } else if (button === '{enter}') {
      const field = $activeField
      // Opt-in (data-submit-on-done): a field like the browser address bar
      // wants "done" to submit, since this keyboard can't send a real Enter.
      if (field?.dataset.submitOnDone !== undefined) {
        field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
      }
      field?.blur()
    }
  }

  onMount(() => {
    keyboard = new Keyboard(keyboardEl, {
      onChange: onKeyboardChange,
      onKeyPress: onKeyPress,
      layoutName: 'default',
      layout: {
        default: [
          '1 2 3 4 5 6 7 8 9 0 {bksp}',
          'q w e r t y u i o p',
          'a s d f g h j k l',
          '{shift} z x c v b n m',
          '{space} {enter}',
        ],
        shift: [
          '! @ # $ % ^ & * ( ) {bksp}',
          'Q W E R T Y U I O P',
          'A S D F G H J K L',
          '{shift} Z X C V B N M',
          '{space} {enter}',
        ],
      },
      display: {
        '{bksp}': '⌫',
        '{enter}': 'done',
        '{shift}': '⇧',
        '{space}': ' ',
      },
    })
  })

  onDestroy(() => keyboard?.destroy())

  // Whenever a different field becomes active, seed the keyboard's
  // internal buffer from that field's current value (e.g. editing an
  // existing title, not just typing a new one).
  $effect(() => {
    if ($activeField) {
      keyboard?.setInput($activeField.value ?? '')
    }
  })
</script>

<div
  class="keyboard-wrap"
  class:visible
  onmousedown={(e) => e.preventDefault()}
  ontouchstart={(e) => e.preventDefault()}
>
  <div bind:this={keyboardEl} class="simple-keyboard"></div>
</div>

<style>
  .keyboard-wrap {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    transform: translateY(100%);
    opacity: 0;
    transition:
      transform 0.2s ease,
      opacity 0.2s ease;
    z-index: 2000;
    pointer-events: none;
    background: #1f2028;
    padding: 0.5rem 0.5rem 0.75rem;
  }

  .keyboard-wrap.visible {
    transform: translateY(0);
    opacity: 1;
    pointer-events: auto;
  }

  .simple-keyboard {
    max-width: 40rem;
    margin: 0 auto;
  }

  /* simple-keyboard's default key height is 40px, which is tiny on this
     1440x2560 kiosk panel — size it for a fingertip instead. Anchored on
     .keyboard-wrap rather than .simple-keyboard because the library
     overwrites its container's class list on init, which strips the
     scoping class Svelte adds to that element. */
  .keyboard-wrap :global(.hg-button) {
    height: 3.5rem;
  }
</style>
