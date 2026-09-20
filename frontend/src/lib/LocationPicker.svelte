<script>
  import { onMount } from 'svelte'
  import { vkbd } from './keyboard/vkbd.js'
  import { trackOverlay } from './overlays.js'
  import { addLocation, deleteLocation, getLocations, searchLocations, selectLocation } from './api.js'

  let { onClose, onChanged } = $props()

  const SEARCH_DEBOUNCE_MS = 400

  let saved = $state([])
  let query = $state('')
  let results = $state([])
  let searching = $state(false)
  let searched = $state(false)
  let error = $state(null)
  let busy = $state(false)
  let debounceTimer

  async function loadSaved() {
    try {
      saved = (await getLocations()).locations
    } catch (err) {
      error = err.message
    }
  }

  // While open, the Browser tab's separate window must get out of the way.
  onMount(() => {
    loadSaved()
    return trackOverlay()
  })

  async function runSearch() {
    const text = query.trim()
    if (text.length < 2) {
      results = []
      searched = false
      return
    }
    searching = true
    error = null
    try {
      results = await searchLocations(text)
      searched = true
    } catch (err) {
      error = err.message
      results = []
    } finally {
      searching = false
    }
  }

  // Search as you type — the on-screen keyboard's "done" key just blurs the
  // field (no Enter event), so waiting on a submit would never fire.
  function onQueryInput() {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(runSearch, SEARCH_DEBOUNCE_MS)
  }

  async function choose(action) {
    busy = true
    error = null
    try {
      const state = await action()
      onChanged(state)
      onClose()
    } catch (err) {
      error = err.message
    } finally {
      busy = false
    }
  }

  function pickResult(candidate) {
    choose(() => addLocation(candidate))
  }

  function pickSaved(location) {
    if (location.is_current) {
      onClose()
      return
    }
    choose(() => selectLocation(location.id))
  }

  async function remove(location) {
    error = null
    try {
      await deleteLocation(location.id)
      await loadSaved()
    } catch (err) {
      error = err.message
    }
  }

  // last_selected_at is naive UTC from the backend (no "Z"), so add it back
  // before parsing or the browser would read it as local time.
  function formatUsed(timestamp) {
    const days = Math.floor((Date.now() - Date.parse(`${timestamp}Z`)) / 86_400_000)
    if (days < 1) return 'today'
    if (days === 1) return 'yesterday'
    if (days < 60) return `${days} days ago`
    return `${Math.round(days / 30)} months ago`
  }
</script>

<div class="overlay" role="presentation" onclick={onClose}>
  <div class="modal" role="dialog" aria-modal="true" aria-label="Weather location" onclick={(e) => e.stopPropagation()}>
    <h3>Weather location</h3>

    <div class="search">
      <input
        type="text"
        placeholder="Search for a city…"
        bind:value={query}
        oninput={onQueryInput}
        use:vkbd
      />
    </div>

    {#if error}
      <p class="error">{error}</p>
    {/if}

    {#if searching}
      <p class="muted">Searching…</p>
    {:else if searched}
      {#if results.length === 0}
        <p class="muted">No places found for “{query.trim()}”.</p>
      {:else}
        <ul class="list">
          {#each results as candidate (candidate.name + candidate.latitude + candidate.longitude)}
            <li>
              <button type="button" class="row" disabled={busy} onclick={() => pickResult(candidate)}>
                {candidate.name}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}

    <h4>Recent locations</h4>
    <ul class="list">
      {#each saved as location (location.id)}
        <li class="saved">
          <button type="button" class="row" disabled={busy} onclick={() => pickSaved(location)}>
            <span class="name">{location.name}</span>
            {#if location.is_current}
              <span class="pill">showing now</span>
            {:else}
              <span class="used">{formatUsed(location.last_selected_at)}</span>
            {/if}
          </button>
          {#if !location.is_current}
            <button
              type="button"
              class="remove"
              aria-label="Remove {location.name}"
              onclick={() => remove(location)}
            >
              ✕
            </button>
          {/if}
        </li>
      {/each}
    </ul>

    <p class="note">Locations you haven't picked in a year are removed automatically.</p>

    <button type="button" class="close" onclick={onClose}>Close</button>
  </div>
</div>

<style>
  /* Anchored near the top rather than centered: the on-screen keyboard rises
     over the bottom of the screen while the search field is focused, and a
     centered tall modal would slide underneath it. */
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 6vh;
    z-index: 1000;
  }

  .modal {
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(92vw, 40rem);
    max-height: 62vh;
    overflow-y: auto;
  }

  h3 {
    margin: 0 0 0.75rem;
  }

  h4 {
    margin: 1.25rem 0 0.5rem;
    opacity: 0.7;
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .search input {
    width: 100%;
    font-size: 1.1rem;
    padding: 0.7rem 0.9rem;
    border: 1px solid #bbb;
    border-radius: 0.5rem;
  }

  .list {
    list-style: none;
    margin: 0.5rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .saved {
    display: flex;
    align-items: stretch;
    gap: 0.4rem;
  }

  .row {
    flex: 1;
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    min-height: 3.2rem;
    padding: 0.5rem 1rem;
    font-size: 1.05rem;
    text-align: left;
    border: 1px solid #ddd;
    border-radius: 0.5rem;
    background: #fafafa;
    cursor: pointer;
  }

  .row:disabled {
    opacity: 0.6;
    cursor: wait;
  }

  .pill {
    font-size: 0.8rem;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    background: #1f2937;
    color: white;
    white-space: nowrap;
  }

  .used {
    font-size: 0.85rem;
    opacity: 0.6;
    white-space: nowrap;
  }

  .remove {
    width: 3.2rem;
    border: 1px solid #ddd;
    border-radius: 0.5rem;
    background: #fafafa;
    font-size: 1.1rem;
    cursor: pointer;
  }

  .muted,
  .note {
    opacity: 0.65;
    font-size: 0.9rem;
  }

  .error {
    color: #c0392b;
  }

  .close {
    margin-top: 0.75rem;
    width: 100%;
    min-height: 3.2rem;
    font-size: 1.05rem;
    border: 1px solid #ccc;
    border-radius: 0.5rem;
    background: #f2f2f2;
    cursor: pointer;
  }
</style>
