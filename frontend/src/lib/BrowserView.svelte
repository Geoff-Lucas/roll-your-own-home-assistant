<script>
  import { onDestroy, onMount } from 'svelte'
  import { vkbd } from './keyboard/vkbd.js'
  import { activeField } from './keyboard/activeField.js'
  import { overlayOpen } from './overlays.js'
  import {
    browserBack,
    browserForward,
    browserReload,
    getBrowserState,
    hideBrowser,
    importCurrentPage,
    navigateBrowser,
    showBrowser,
  } from './api.js'

  let { onOpenRecipes } = $props()

  const POLL_MS = 1500
  // The on-screen keyboard slides in over 0.2s; measure after it has landed.
  const SETTLE_MS = 300

  // The page itself is not part of this component: it's a separate Chromium
  // window that the backend lays over the `stage` box below (see
  // app/browser/). This component is the toolbar plus that box's geometry.
  let stage
  let address = $state('')
  let browser = $state({ running: false, url: null, title: null, can_go_back: false, can_go_forward: false })
  let starting = $state(true)
  let unavailable = $state(null)
  let notice = $state(null)
  let addingRecipe = $state(false)
  let addressFocused = false
  let pollTimer
  let settleTimer
  let observer

  // Hide the window while a dialog is open — it would sit on top of it.
  const covered = $derived($overlayOpen)

  function stageRect() {
    const box = stage.getBoundingClientRect()
    const scale = window.devicePixelRatio || 1
    // Screen position of the page's top-left (the kiosk window is frameless
    // at 0,0, so the offsets are normally zero).
    const originX = window.screenX
    const originY = window.screenY + (window.outerHeight - window.innerHeight)
    // While the on-screen keyboard is up (typing in the address bar), stop the
    // browser window above it — otherwise it would cover the keyboard.
    const keyboard = document.querySelector('.keyboard-wrap.visible')
    const bottom = keyboard ? Math.min(box.bottom, keyboard.getBoundingClientRect().top) : box.bottom
    return {
      x: Math.max(0, Math.round(originX + box.left * scale)),
      y: Math.max(0, Math.round(originY + box.top * scale)),
      width: Math.max(1, Math.round(box.width * scale)),
      height: Math.max(1, Math.round((bottom - box.top) * scale)),
    }
  }

  async function sync() {
    if (!stage) return
    try {
      if (covered) {
        await hideBrowser()
        return
      }
      browser = await showBrowser(stageRect())
      unavailable = null
    } catch (err) {
      // 503 = this machine can't run the browser window at all; anything else
      // is worth a visible (but dismissable) note.
      unavailable = err.message
    } finally {
      starting = false
    }
  }

  function scheduleSync() {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(sync, SETTLE_MS)
  }

  // Re-place the window whenever a dialog opens/closes or the keyboard moves.
  $effect(() => {
    covered
    $activeField
    scheduleSync()
  })

  async function poll() {
    if (covered || unavailable || starting) return
    try {
      browser = await getBrowserState()
      if (!addressFocused) address = browser.url ?? ''
    } catch {
      // A missed poll isn't worth surfacing; the next one will catch up.
    }
  }

  onMount(() => {
    observer = new ResizeObserver(scheduleSync)
    observer.observe(stage)
    pollTimer = setInterval(poll, POLL_MS)
  })

  onDestroy(() => {
    observer?.disconnect()
    clearInterval(pollTimer)
    clearTimeout(settleTimer)
    // Leaving the tab must take the separate window away with it.
    hideBrowser().catch(() => {})
  })

  function fail(err) {
    notice = { kind: 'error', text: err.message }
  }

  async function go() {
    const text = address.trim()
    if (!text) return
    notice = null
    try {
      browser = await navigateBrowser(text)
    } catch (err) {
      fail(err)
    }
  }

  function onAddressKeydown(event) {
    if (event.key === 'Enter') {
      event.preventDefault()
      go()
    }
  }

  async function step(action) {
    notice = null
    try {
      browser = await action()
    } catch (err) {
      fail(err)
    }
  }

  async function addRecipe() {
    addingRecipe = true
    notice = null
    try {
      const recipe = await importCurrentPage()
      notice = { kind: 'ok', text: `Added “${recipe.title}” to your recipes`, canView: true }
    } catch (err) {
      fail(err)
    } finally {
      addingRecipe = false
    }
  }
</script>

<div class="browser-view">
  <div class="toolbar">
    <button type="button" class="nav" aria-label="Back" disabled={!browser.can_go_back} onclick={() => step(browserBack)}>
      ‹
    </button>
    <button
      type="button"
      class="nav"
      aria-label="Forward"
      disabled={!browser.can_go_forward}
      onclick={() => step(browserForward)}
    >
      ›
    </button>
    <button type="button" class="nav" aria-label="Reload" onclick={() => step(browserReload)}>⟳</button>

    <input
      class="address"
      type="text"
      placeholder="Search or type a web address"
      bind:value={address}
      onkeydown={onAddressKeydown}
      onfocus={() => (addressFocused = true)}
      onblur={() => (addressFocused = false)}
      data-submit-on-done
      use:vkbd
    />
    <button type="button" class="go" onclick={go}>Go</button>

    <button type="button" class="add" disabled={addingRecipe || !browser.running} onclick={addRecipe}>
      {addingRecipe ? 'Adding…' : '＋ Add to recipes'}
    </button>
  </div>

  {#if notice}
    <div class="notice {notice.kind}">
      <span>{notice.text}</span>
      {#if notice.canView}
        <button type="button" onclick={onOpenRecipes}>View recipes</button>
      {/if}
      <button type="button" aria-label="Dismiss" onclick={() => (notice = null)}>✕</button>
    </div>
  {/if}

  <div class="stage" bind:this={stage}>
    {#if unavailable}
      <p class="status">The browser isn't available: {unavailable}</p>
    {:else if starting}
      <p class="status">Starting browser…</p>
    {/if}
  </div>
</div>

<style>
  .browser-view {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    height: 100%;
  }

  .toolbar {
    display: flex;
    gap: 0.5rem;
    align-items: stretch;
  }

  .toolbar button,
  .address {
    min-height: 3.2rem;
    font-size: 1.05rem;
    border-radius: 0.5rem;
    border: 1px solid #ccc;
  }

  .toolbar button {
    padding: 0 1rem;
    background: #f2f2f2;
    cursor: pointer;
  }

  .toolbar button:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .nav {
    width: 3.4rem;
    padding: 0;
    font-size: 1.5rem;
  }

  .address {
    flex: 1;
    min-width: 0;
    padding: 0 0.9rem;
  }

  .go {
    background: #1f2937 !important;
    color: white;
    border-color: #1f2937 !important;
  }

  .add {
    background: #1d4ed8 !important;
    color: white;
    border-color: #1d4ed8 !important;
    white-space: nowrap;
  }

  .notice {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.9rem;
    border-radius: 0.5rem;
    font-size: 1rem;
  }

  .notice span {
    flex: 1;
  }

  .notice.ok {
    background: #e6f4ea;
    color: #14532d;
  }

  .notice.error {
    background: #fdecea;
    color: #8a1c14;
  }

  .notice button {
    min-height: 2.4rem;
    padding: 0 0.9rem;
    border: 1px solid currentColor;
    border-radius: 0.4rem;
    background: transparent;
    color: inherit;
    cursor: pointer;
  }

  /* Empty on purpose: the browser window is laid over this box. Only the
     status text below is ever visible, and only until the window appears. */
  .stage {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f3f4f6;
    border-radius: 0.5rem;
  }

  .status {
    opacity: 0.6;
    padding: 0 2rem;
    text-align: center;
  }
</style>
