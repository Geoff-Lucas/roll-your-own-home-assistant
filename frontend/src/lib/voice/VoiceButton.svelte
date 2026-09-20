<script>
  import { onMount } from 'svelte'
  import { getVoiceStatus } from '../api.js'
  import { startListening } from './store.js'

  // When the wake word is live, say so: it is the difference between "tap me"
  // and "just talk", and it should be obvious the microphone is being watched.
  let phrase = $state(null)

  onMount(async () => {
    try {
      const { wake_word } = await getVoiceStatus()
      if (wake_word?.enabled) phrase = wake_word.phrase
    } catch {
      // No status, no hint — the button still works.
    }
  })
</script>

<button type="button" class="mic" aria-label="Talk to the assistant" onclick={startListening}>
  🎤{#if phrase}<span class="phrase">“{phrase}”</span>{/if}
</button>

<style>
  .mic {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-height: 2.7rem;
    min-width: 2.7rem;
    padding: 0 0.85rem;
    border-radius: 999px;
    border: 1px solid #c7d2fe;
    background: #eef2ff;
    font-size: 1.25rem;
    cursor: pointer;
  }

  .phrase {
    font-size: 0.95rem;
    color: #3730a3;
    opacity: 0.85;
  }
</style>
