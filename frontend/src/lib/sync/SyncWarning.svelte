<script>
  // A chip in the header when a calendar has stopped syncing, so a frozen
  // calendar can't go unnoticed; tap it for what's wrong and, for an expired
  // Google sign-in, a button that opens the sign-in in the Browser tab.
  import { onDestroy, onMount } from 'svelte'
  import { getSyncProblems } from '../api.js'
  import { trackOverlay } from '../overlays.js'
  import { chipText, describeProblem } from './problems.js'

  let { onOpenInBrowser } = $props()

  const POLL_MS = 60_000 // sync itself only runs every 5 minutes
  let problems = $state([])
  let open = $state(false)
  let timer

  async function refresh() {
    try {
      problems = await getSyncProblems()
      if (problems.length === 0) open = false
    } catch {
      // Can't ask right now; keep showing what we last knew.
    }
  }

  onMount(() => {
    refresh()
    timer = setInterval(refresh, POLL_MS)
  })
  onDestroy(() => clearInterval(timer))

  // The Browser tab's window sits on top of everything; hide it while this is open.
  $effect(() => {
    if (open) return trackOverlay()
  })

  function fix(url) {
    open = false
    onOpenInBrowser(url)
  }
</script>

{#if problems.length}
  <button type="button" class="chip" onclick={() => (open = true)}>{chipText(problems)}</button>
{/if}

{#if open}
  <div class="overlay" role="presentation" onclick={() => (open = false)}>
    <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label="Calendar sync problems"
         onclick={(e) => e.stopPropagation()}>
      {#each problems as problem (problem.account_id)}
        {@const shown = describeProblem(problem)}
        <section>
          <h3>{shown.title}</h3>
          <p>{shown.detail}</p>
          <p class="stale">{shown.stale}</p>
          {#if shown.fix}
            <button type="button" class="primary" onclick={() => fix(shown.fix)}>Sign in to Google again</button>
            <p class="hint">Opens in the Browser tab. Use the same Google account; the calendar catches up within a few minutes.</p>
          {/if}
        </section>
      {/each}
      <div class="actions">
        <button type="button" onclick={() => (open = false)}>Close</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .chip {
    font-size: 0.95rem;
    padding: 0.4rem 0.9rem;
    border-radius: 999px;
    border: 1px solid #f59e0b;
    background: #fef3c7;
    color: #92400e;
    cursor: pointer;
  }

  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(90vw, 32rem);
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  section + section {
    border-top: 1px solid #eee;
    padding-top: 1rem;
  }

  h3 {
    margin: 0 0 0.4rem;
  }

  p {
    margin: 0 0 0.5rem;
  }

  .stale,
  .hint {
    color: #666;
    font-size: 0.9rem;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
  }

  button {
    font-size: 1rem;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
  }

  button.primary {
    background: #2563eb;
    color: white;
    border-color: #2563eb;
    margin-bottom: 0.4rem;
  }
</style>
