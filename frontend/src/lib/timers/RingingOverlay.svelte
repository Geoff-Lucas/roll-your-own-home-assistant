<script>
  import { onMount } from 'svelte'
  import { getVoiceStatus } from '../api.js'
  import { trackOverlay } from '../overlays.js'
  import { act, formatAlarmTime, ICONS, itemName, ringing } from './store.js'

  let busy = $state(false)
  let error = $state(null)
  // Whether "stop" / "snooze" can be said instead of tapped (needs speech recognition).
  let canSpeak = $state(false)

  onMount(async () => {
    try {
      canSpeak = (await getVoiceStatus()).ring_commands === true
    } catch {
      // No hint if the status can't be read; the buttons still work.
    }
  })

  // A boolean, not the list: `ringing` gets a fresh array on every clock tick,
  // and this must only fire when something starts or stops ringing.
  const active = $derived($ringing.length > 0)

  // The alert has to appear above the Browser tab's separate window too.
  $effect(() => {
    if (active) return trackOverlay()
  })

  async function run(action) {
    busy = true
    error = null
    try {
      await action()
    } catch (err) {
      error = err.message
    } finally {
      busy = false
    }
  }

  const dismiss = (item) => run(() => act(item.id, 'dismiss'))
  const snooze = (item, minutes) => run(() => act(item.id, 'snooze', { minutes }))
</script>

{#if active}
  <div class="overlay" role="alertdialog" aria-modal="true" aria-label="Timer finished">
    <div class="cards">
      {#each $ringing as item (item.id)}
        <div class="card">
          <div class="icon">{ICONS[item.kind]}</div>
          <h2>{itemName(item)}</h2>
          <p>{item.kind === 'alarm' ? formatAlarmTime(item.alarm_time) : "Time's up"}</p>
          <div class="actions">
            <button type="button" class="dismiss" disabled={busy} onclick={() => dismiss(item)}>Dismiss</button>
            {#if item.kind === 'alarm'}
              <button type="button" disabled={busy} onclick={() => snooze(item, 5)}>Snooze 5 min</button>
              <button type="button" disabled={busy} onclick={() => snooze(item, 10)}>Snooze 10 min</button>
            {:else}
              <button type="button" disabled={busy} onclick={() => snooze(item, 1)}>＋1 min</button>
              <button type="button" disabled={busy} onclick={() => snooze(item, 5)}>＋5 min</button>
            {/if}
          </div>
        </div>
      {/each}
      {#if canSpeak}<p class="hint">…or just say “stop” or “snooze”</p>{/if}
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  /* Above everything: the dim overlay (1500), the keyboard (2000), dialogs. */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 3000;
    background: rgba(17, 24, 39, 0.88);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }

  .cards {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    width: min(90vw, 44rem);
  }

  .card {
    background: white;
    color: #111;
    border-radius: 1rem;
    padding: 2rem;
    text-align: center;
    animation: pulse 1.2s ease-in-out infinite;
  }

  .icon {
    font-size: 4.5rem;
    line-height: 1;
  }

  h2 {
    margin: 0.5rem 0 0;
    font-size: 2.2rem;
  }

  p {
    margin: 0.25rem 0 1.25rem;
    font-size: 1.4rem;
    opacity: 0.7;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
  }

  button {
    flex: 1;
    min-width: 9rem;
    min-height: 4.5rem;
    font: inherit;
    font-size: 1.3rem;
    border-radius: 0.75rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
    cursor: pointer;
  }

  .dismiss {
    flex: 2;
    background: #dc2626;
    border-color: #dc2626;
    color: white;
    font-weight: 700;
  }

  .error {
    color: #fecaca;
    text-align: center;
  }

  .hint {
    color: #d1d5db;
    text-align: center;
    font-size: 1.2rem;
    margin: 0;
  }

  /* Gentle, not a flash: this may go off in a dim room. */
  @keyframes pulse {
    0%,
    100% {
      box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.55);
    }
    50% {
      box-shadow: 0 0 0 1.2rem rgba(220, 38, 38, 0);
    }
  }
</style>
