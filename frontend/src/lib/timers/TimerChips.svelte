<script>
  import { timers, formatClock, formatAlarmTime, ICONS } from './store.js'
  import TimerPanel from './TimerPanel.svelte'

  const MAX_CHIPS = 3

  let open = $state(false)

  const shown = $derived($timers.slice(0, MAX_CHIPS))
  const hidden = $derived(Math.max(0, $timers.length - MAX_CHIPS))

  function chipText(item) {
    if (item.kind === 'stopwatch') return formatClock(item.elapsed_seconds, { countdown: false })
    if (item.kind === 'alarm') return formatAlarmTime(item.alarm_time)
    return formatClock(item.remaining_seconds)
  }
</script>

<div class="timer-area">
  {#each shown as item (item.id)}
    <button type="button" class="chip" class:paused={item.state === 'paused'} onclick={() => (open = true)}>
      <span class="icon">{ICONS[item.kind]}</span>
      {#if item.label}<span class="label">{item.label}</span>{/if}
      <span class="time">{chipText(item)}</span>
    </button>
  {/each}
  {#if hidden > 0}
    <button type="button" class="chip more" onclick={() => (open = true)}>+{hidden}</button>
  {/if}
  <button type="button" class="open" aria-label="Timers, alarms and stopwatch" onclick={() => (open = true)}>
    {$timers.length === 0 ? '⏱ Timers' : '＋'}
  </button>
</div>

{#if open}
  <TimerPanel onClose={() => (open = false)} />
{/if}

<style>
  .timer-area {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .chip,
  .open {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-height: 2.7rem;
    padding: 0 0.9rem;
    border-radius: 999px;
    border: 1px solid #c7d2fe;
    background: #eef2ff;
    color: #1e1b4b;
    font: inherit;
    font-size: 1rem;
    cursor: pointer;
  }

  .chip .time {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .chip .label {
    max-width: 8rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chip.paused {
    opacity: 0.6;
  }

  .open {
    background: #f2f2f2;
    border-color: #ccc;
    color: inherit;
  }
</style>
