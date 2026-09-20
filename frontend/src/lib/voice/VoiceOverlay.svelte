<script>
  import { trackOverlay } from '../overlays.js'
  import { closeVoice, finishListening, startListening, voice, voiceOpen } from './store.js'

  const STATUS = {
    listening: 'Listening…',
    transcribing: 'Working out what you said…',
    thinking: 'Thinking…',
    speaking: 'Speaking…',
  }

  // A boolean, so it only fires when the panel opens or closes — see the note
  // in RingingOverlay: the browser window has to get out of the way of it.
  const open = $derived($voiceOpen)
  $effect(() => {
    if (open) return trackOverlay()
  })

  const busy = $derived(['listening', 'transcribing', 'thinking', 'speaking'].includes($voice.state))
  // The ring breathes with the volume of your voice.
  const scale = $derived(1 + Math.min(1, $voice.level) * 0.7)
</script>

{#if open}
  <div class="overlay" role="dialog" aria-modal="true" aria-label="Voice assistant">
    <div class="panel">
      <div class="mic" class:live={$voice.state === 'listening'}>
        <div class="ring" style="transform: scale({scale})"></div>
        <span class="glyph">🎤</span>
      </div>

      {#if busy}
        <p class="status">{STATUS[$voice.state]}</p>
      {/if}

      {#if $voice.transcript}
        <p class="heard">“{$voice.transcript}”</p>
      {:else if $voice.state === 'listening'}
        <p class="hint">Try “set a timer for ten minutes” or “what’s the weather?”</p>
      {/if}

      {#if $voice.reply}
        <p class="reply" class:unsure={$voice.understood === false}>{$voice.reply}</p>
      {/if}
      {#if $voice.error}
        <p class="error">{$voice.error}</p>
      {/if}

      <div class="actions">
        {#if $voice.state === 'listening'}
          <button type="button" class="primary" onclick={finishListening}>Done talking</button>
        {:else if !busy}
          <button type="button" onclick={startListening}>Ask again</button>
          <button type="button" class="primary" onclick={closeVoice}>Close</button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  /* Above dialogs and the keyboard, below the timer alert: a ringing timer
     always wins the screen. */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 2500;
    background: rgba(17, 24, 39, 0.82);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }

  .panel {
    background: white;
    color: #111;
    border-radius: 1.2rem;
    padding: 2.2rem 2rem;
    width: min(90vw, 40rem);
    text-align: center;
  }

  .mic {
    position: relative;
    width: 8rem;
    height: 8rem;
    margin: 0 auto 1rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: #dbeafe;
    transition: transform 0.12s ease-out;
  }

  .live .ring {
    background: #fecaca;
  }

  .glyph {
    position: relative;
    font-size: 3.2rem;
  }

  p {
    margin: 0.4rem 0;
  }

  .status {
    font-size: 1.3rem;
    opacity: 0.7;
  }

  .heard {
    font-size: 1.5rem;
    font-style: italic;
  }

  .hint {
    opacity: 0.55;
  }

  .reply {
    font-size: 1.9rem;
    font-weight: 700;
    margin-top: 1rem;
  }

  .reply.unsure {
    color: #92400e;
  }

  .error {
    font-size: 1.3rem;
    color: #b91c1c;
    margin-top: 1rem;
  }

  .actions {
    display: flex;
    gap: 0.75rem;
    margin-top: 1.6rem;
  }

  button {
    flex: 1;
    min-height: 4rem;
    font: inherit;
    font-size: 1.2rem;
    border-radius: 0.75rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
    cursor: pointer;
  }

  .primary {
    background: #1d4ed8;
    border-color: #1d4ed8;
    color: white;
    font-weight: 700;
  }
</style>
