<script>
  import { onMount } from 'svelte'
  import { getLocations } from './api.js'
  import { locationVersion } from './weatherLocation.js'
  import LocationPicker from './LocationPicker.svelte'

  let name = $state(null)
  let open = $state(false)

  function applyState(state) {
    name = state.locations.find((location) => location.is_current)?.name ?? null
  }

  onMount(async () => {
    try {
      applyState(await getLocations())
    } catch {
      // Leave the badge on its placeholder; tapping it still opens the picker.
    }
  })

  function handleChanged(state) {
    applyState(state)
    locationVersion.update((version) => version + 1)
  }
</script>

<button type="button" class="badge" onclick={() => (open = true)}>
  <span class="place">{name ?? 'Set location'}</span>
  <span class="hint">📍 Change ›</span>
</button>

{#if open}
  <LocationPicker onClose={() => (open = false)} onChanged={handleChanged} />
{/if}

<style>
  .badge {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.25rem;
    align-self: stretch;
    max-width: 12rem;
    padding: 0 0 0 1.25rem;
    border: none;
    border-left: 1px solid rgba(128, 128, 128, 0.35);
    background: none;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .place {
    font-size: 1.15rem;
    font-weight: 600;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .hint {
    font-size: 0.85rem;
    opacity: 0.6;
  }
</style>
