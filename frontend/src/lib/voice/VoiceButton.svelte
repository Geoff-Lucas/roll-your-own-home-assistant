<script>
  import { startListening } from './store.js'
</script>

<button type="button" class="mic" aria-label="Talk to the assistant" onclick={startListening}>🎤</button>

<style>
  .mic {
    min-height: 2.7rem;
    min-width: 2.7rem;
    padding: 0 0.7rem;
    border-radius: 999px;
    border: 1px solid #c7d2fe;
    background: #eef2ff;
    font-size: 1.25rem;
    cursor: pointer;
  }
</style>
