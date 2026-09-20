<script>
  import { onMount } from 'svelte'
  import { vkbd } from '../keyboard/vkbd.js'
  import { trackOverlay } from '../overlays.js'
  import { act, create, formatAlarmTime, formatClock, ICONS, itemName, remove, repeatLabel, timers } from './store.js'

  let { onClose } = $props()

  const PRESET_MINUTES = [1, 3, 5, 10, 15, 20, 30, 45, 60]

  let mode = $state('timer') // timer | alarm | stopwatch
  let label = $state('')
  let error = $state(null)
  let busy = $state(false)

  // Custom timer length
  let hours = $state(0)
  let minutes = $state(5)
  let seconds = $state(0)

  // Alarm
  let alarmHour = $state(7) // 1-12
  let alarmMinute = $state(0)
  let pm = $state(false)
  let repeat = $state('none')

  // Everything here hides the Browser tab's separate window while open.
  onMount(() => trackOverlay())

  const step = (value, delta, min, max) => Math.min(max, Math.max(min, value + delta))
  const wrap = (value, delta, size) => (((value + delta) % size) + size) % size
  const pad = (n) => String(n).padStart(2, '0')

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

  const startPreset = (mins) => run(() => create({ kind: 'timer', seconds: mins * 60, label: label.trim() }))

  function startCustom() {
    const total = hours * 3600 + minutes * 60 + seconds
    if (total < 1) {
      error = 'Set a length first'
      return
    }
    run(() => create({ kind: 'timer', seconds: total, label: label.trim() }))
  }

  function startAlarm() {
    const hour24 = (alarmHour % 12) + (pm ? 12 : 0)
    run(() => create({ kind: 'alarm', time: `${pad(hour24)}:${pad(alarmMinute)}`, repeat, label: label.trim() }))
  }

  const startStopwatch = () => run(() => create({ kind: 'stopwatch', label: label.trim() }))
</script>

<div class="overlay" role="presentation" onclick={onClose}>
  <div class="modal" role="dialog" aria-modal="true" aria-label="Timers" onclick={(e) => e.stopPropagation()}>
    <h3>Timers &amp; alarms</h3>

    {#if $timers.length > 0}
      <ul class="items">
        {#each $timers as item (item.id)}
          <li class:ringing={item.state === 'ringing'}>
            <div class="what">
              <span class="name">{ICONS[item.kind]} {itemName(item)}</span>
              {#if item.kind === 'alarm'}
                <span class="sub">
                  {item.state === 'ringing' ? 'ringing' : `in ${formatClock(item.remaining_seconds)}`}
                  {repeatLabel(item) ? ` · ${repeatLabel(item)}` : ''}
                </span>
              {:else if item.state === 'paused'}
                <span class="sub">paused</span>
              {:else if item.state === 'ringing'}
                <span class="sub">time's up</span>
              {/if}
            </div>
            <span class="big">
              {#if item.kind === 'stopwatch'}
                {formatClock(item.elapsed_seconds, { countdown: false })}
              {:else if item.kind === 'alarm'}
                {formatAlarmTime(item.alarm_time)}
              {:else}
                {formatClock(item.remaining_seconds)}
              {/if}
            </span>
            <div class="controls">
              {#if item.state === 'running' && item.kind !== 'alarm'}
                <button type="button" onclick={() => run(() => act(item.id, 'pause'))}>Pause</button>
              {:else if item.state === 'paused'}
                <button type="button" onclick={() => run(() => act(item.id, 'resume'))}>Resume</button>
              {/if}
              {#if item.kind === 'stopwatch'}
                <button type="button" onclick={() => run(() => act(item.id, 'reset'))}>Reset</button>
              {/if}
              <button type="button" class="danger" aria-label="Remove" onclick={() => run(() => remove(item.id))}>
                ✕
              </button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}

    <div class="modes">
      {#each [['timer', '⏱ Timer'], ['alarm', '⏰ Alarm'], ['stopwatch', '⏲ Stopwatch']] as [id, text] (id)}
        <button type="button" class:active={mode === id} onclick={() => (mode = id)}>{text}</button>
      {/each}
    </div>

    {#if mode === 'timer'}
      <div class="presets">
        {#each PRESET_MINUTES as mins (mins)}
          <button type="button" disabled={busy} onclick={() => startPreset(mins)}>{mins} min</button>
        {/each}
      </div>
      <div class="custom">
        {#each [['hours', 'h', 0, 99], ['minutes', 'm', 0, 59], ['seconds', 's', 0, 59]] as [field, unit, lo, hi] (field)}
          {@const value = field === 'hours' ? hours : field === 'minutes' ? minutes : seconds}
          <div class="stepper">
            <button
              type="button"
              aria-label="More {field}"
              onclick={() => {
                const next = step(value, field === 'seconds' ? 5 : 1, lo, hi)
                if (field === 'hours') hours = next
                else if (field === 'minutes') minutes = next
                else seconds = next
              }}>▲</button
            >
            <span class="value">{pad(value)}<small>{unit}</small></span>
            <button
              type="button"
              aria-label="Fewer {field}"
              onclick={() => {
                const next = step(value, field === 'seconds' ? -5 : -1, lo, hi)
                if (field === 'hours') hours = next
                else if (field === 'minutes') minutes = next
                else seconds = next
              }}>▼</button
            >
          </div>
        {/each}
        <button type="button" class="start" disabled={busy} onclick={startCustom}>Start</button>
      </div>
    {:else if mode === 'alarm'}
      <div class="custom">
        <div class="stepper">
          <button type="button" aria-label="Later hour" onclick={() => (alarmHour = wrap(alarmHour - 1, 1, 12) + 1)}>▲</button>
          <span class="value">{alarmHour}</span>
          <button type="button" aria-label="Earlier hour" onclick={() => (alarmHour = wrap(alarmHour - 1, -1, 12) + 1)}>▼</button>
        </div>
        <span class="colon">:</span>
        <div class="stepper">
          <button type="button" aria-label="Later minute" onclick={() => (alarmMinute = wrap(alarmMinute, 5, 60))}>▲</button>
          <span class="value">{pad(alarmMinute)}</span>
          <button type="button" aria-label="Earlier minute" onclick={() => (alarmMinute = wrap(alarmMinute, -5, 60))}>▼</button>
        </div>
        <button type="button" class="ampm" onclick={() => (pm = !pm)}>{pm ? 'PM' : 'AM'}</button>
        <select bind:value={repeat} aria-label="Repeat">
          <option value="none">Once</option>
          <option value="daily">Every day</option>
          <option value="weekdays">Weekdays</option>
        </select>
        <button type="button" class="start" disabled={busy} onclick={startAlarm}>Set alarm</button>
      </div>
    {:else}
      <div class="custom">
        <button type="button" class="start wide" disabled={busy} onclick={startStopwatch}>Start stopwatch</button>
      </div>
    {/if}

    <input type="text" class="label" placeholder="Name (optional), e.g. pasta" maxlength="60" bind:value={label} use:vkbd />

    {#if error}<p class="error">{error}</p>{/if}

    <button type="button" class="close" onclick={onClose}>Close</button>
  </div>
</div>

<style>
  /* Near the top, not centered: the on-screen keyboard rises over the bottom
     of the screen while the name field is focused. */
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
    width: min(92vw, 44rem);
    max-height: 66vh;
    overflow-y: auto;
  }

  h3 {
    margin: 0 0 0.75rem;
  }

  button,
  select,
  .label {
    min-height: 3.2rem;
    font: inherit;
    font-size: 1.05rem;
    border-radius: 0.5rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.5;
  }

  .items {
    list-style: none;
    margin: 0 0 1rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .items li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid #ddd;
    border-radius: 0.6rem;
    background: #fafafa;
  }

  .items li.ringing {
    border-color: #dc2626;
    background: #fef2f2;
  }

  .what {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub {
    font-size: 0.85rem;
    opacity: 0.65;
  }

  .big {
    font-size: 1.6rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .controls {
    display: flex;
    gap: 0.4rem;
  }

  .controls button {
    padding: 0 0.9rem;
  }

  .danger {
    width: 3.2rem;
    padding: 0;
  }

  .modes {
    display: flex;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
  }

  .modes button {
    flex: 1;
  }

  .modes .active {
    background: #1f2937;
    border-color: #1f2937;
    color: white;
  }

  .presets {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(6.5rem, 1fr));
    gap: 0.4rem;
    margin-bottom: 0.75rem;
  }

  .custom {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }

  .stepper {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.2rem;
  }

  .stepper button {
    width: 4rem;
    min-height: 2.6rem;
  }

  .value {
    font-size: 2rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .value small {
    font-size: 0.9rem;
    opacity: 0.6;
    margin-left: 0.15rem;
  }

  .colon {
    font-size: 2rem;
    font-weight: 700;
  }

  .ampm {
    width: 5rem;
  }

  select {
    padding: 0 0.6rem;
  }

  .start {
    flex: 1;
    background: #1d4ed8;
    border-color: #1d4ed8;
    color: white;
    min-width: 8rem;
  }

  .start.wide {
    min-height: 4rem;
  }

  .label {
    width: 100%;
    padding: 0 0.9rem;
    background: white;
    cursor: text;
  }

  .error {
    color: #c0392b;
  }

  .close {
    width: 100%;
    margin-top: 0.75rem;
  }
</style>
