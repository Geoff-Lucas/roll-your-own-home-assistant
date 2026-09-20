<script>
  import { onMount } from 'svelte'
  import { dismissReminder, getReminders } from './api.js'

  let reminders = $state([])
  let error = $state(null)

  async function load() {
    try {
      reminders = await getReminders()
      error = null
    } catch (err) {
      error = err.message
    }
  }

  async function handleDismiss(eventId) {
    try {
      await dismissReminder(eventId)
      reminders = reminders.filter((r) => r.event_id !== eventId)
    } catch (err) {
      error = err.message
    }
  }

  function whenLabel(daysUntil) {
    if (daysUntil === 0) return 'today'
    if (daysUntil === 1) return 'tomorrow'
    return `in ${daysUntil} days`
  }

  onMount(load)
</script>

<div class="panel">
  <h3>Upcoming to-dos</h3>
  {#if error}
    <p class="error">{error}</p>
  {/if}
  {#if reminders.length === 0 && !error}
    <p class="empty">Nothing coming up.</p>
  {:else}
    <ul>
      {#each reminders as reminder (reminder.event_id)}
        <li>
          <div class="info">
            <strong>{reminder.title}</strong>
            <span class="when">{whenLabel(reminder.days_until)}</span>
            <span class="text">{reminder.text}</span>
          </div>
          <button type="button" class="dismiss" onclick={() => handleDismiss(reminder.event_id)} aria-label="Dismiss">
            ✓
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    background: white;
    border-radius: 0.6rem;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    padding: 0.75rem 1rem;
    overflow: hidden;
  }

  h3 {
    margin: 0 0 0.5rem;
    flex-shrink: 0;
  }

  .empty {
    opacity: 0.6;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    flex: 1;
  }

  li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.7rem 0;
    border-bottom: 1px solid #eee;
  }

  .info {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
  }

  .when {
    font-size: 1.05rem;
    color: #b8860b;
    font-weight: 600;
  }

  .text {
    font-size: 1.05rem;
    opacity: 0.75;
  }

  .dismiss {
    flex-shrink: 0;
    width: 2.75rem;
    height: 2.75rem;
    border-radius: 50%;
    border: 1px solid #ccc;
    background: #f5f5f5;
    cursor: pointer;
    font-size: 1.2rem;
  }

  .error {
    color: #c0392b;
  }
</style>
