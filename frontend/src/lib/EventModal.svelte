<script>
  import { vkbd } from './keyboard/vkbd.js'

  // datetime-local/date inputs keep their native pickers — those are
  // already touch-friendly and don't need a QWERTY keyboard. Only the
  // title field opts into the in-app virtual keyboard (use:vkbd).
  //
  // Also deliberately naive about timezones: datetime-local values carry no
  // offset, and the backend's convention is naive-but-UTC (see
  // app/time_utils.py), so what you type is taken as UTC as-is. Fine for a
  // single-timezone household; revisit if that stops being true.
  let { open, mode, accounts, initial, onSave, onDelete, onClose } = $props()

  let title = $state('')
  let accountId = $state(null)
  let allDay = $state(false)
  let startValue = $state('')
  let endValue = $state('')
  let needsReminder = $state(false)
  let reminderLeadDays = $state(7)
  let reminderText = $state('')
  let error = $state(null)
  let busy = $state(false)

  const writableAccounts = $derived(accounts.filter((a) => a.caldav_url))
  const isRecurring = $derived(Boolean(initial?.rrule))

  $effect(() => {
    if (!open) return
    title = initial?.title ?? ''
    accountId = initial?.accountId ?? writableAccounts[0]?.id ?? null
    allDay = initial?.allDay ?? false
    startValue = initial?.startValue ?? ''
    endValue = initial?.endValue ?? ''
    needsReminder = initial?.reminderLeadDays != null
    reminderLeadDays = initial?.reminderLeadDays ?? 7
    reminderText = initial?.reminderText ?? ''
    error = null
    busy = false
  })

  async function handleSave() {
    error = null
    busy = true
    try {
      const payload = {
        account_id: accountId,
        title,
        all_day: allDay,
        ...(allDay
          ? { start_date: startValue, end_date: endValue }
          : { start_time: startValue, end_time: endValue }),
        reminder_lead_days: needsReminder ? Number(reminderLeadDays) : null,
        reminder_text: needsReminder ? reminderText || null : null,
      }
      await onSave(payload)
    } catch (err) {
      error = err.message
      busy = false
    }
  }

  async function handleDelete() {
    error = null
    busy = true
    try {
      await onDelete()
    } catch (err) {
      error = err.message
      busy = false
    }
  }
</script>

{#if open}
  <div class="overlay" role="presentation" onclick={onClose}>
    <div class="modal" role="dialog" aria-modal="true" onclick={(e) => e.stopPropagation()}>
      <h2>{mode === 'edit' ? 'Edit event' : 'New event'}</h2>

      {#if isRecurring}
        <p class="notice">This is part of a recurring series — editing recurring events isn't supported yet.</p>
        <div class="actions">
          <button type="button" onclick={onClose}>Close</button>
        </div>
      {:else}
        <label>
          Title
          <input type="text" bind:value={title} use:vkbd />
        </label>

        <label>
          Calendar
          <select bind:value={accountId}>
            {#each writableAccounts as account (account.id)}
              <option value={account.id}>{account.person_name} — {account.display_name}</option>
            {/each}
          </select>
        </label>

        <label class="checkbox">
          <input type="checkbox" bind:checked={allDay} />
          All day
        </label>

        {#if allDay}
          <label>
            Start date
            <input type="date" bind:value={startValue} />
          </label>
          <label>
            End date (exclusive)
            <input type="date" bind:value={endValue} />
          </label>
        {:else}
          <label>
            Start
            <input type="datetime-local" bind:value={startValue} />
          </label>
          <label>
            End
            <input type="datetime-local" bind:value={endValue} />
          </label>
        {/if}

        <label class="checkbox">
          <input type="checkbox" bind:checked={needsReminder} />
          Needs a prep reminder (e.g. get a gift)
        </label>

        {#if needsReminder}
          <label>
            Days before to remind me
            <input type="number" min="1" max="60" bind:value={reminderLeadDays} />
          </label>
          <label>
            What to do
            <input type="text" placeholder="e.g. Get a card or gift" bind:value={reminderText} use:vkbd />
          </label>
        {/if}

        {#if error}
          <p class="error">{error}</p>
        {/if}

        <div class="actions">
          {#if mode === 'edit'}
            <button type="button" class="danger" disabled={busy} onclick={handleDelete}>Delete</button>
          {/if}
          <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
          <button type="button" class="primary" disabled={busy || !accountId} onclick={handleSave}>Save</button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
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
    width: min(90vw, 26rem);
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  h2 {
    margin: 0 0 0.25rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.9rem;
  }

  label.checkbox {
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
  }

  input[type='text'],
  input[type='datetime-local'],
  input[type='date'],
  select {
    font-size: 1rem;
    padding: 0.5rem;
  }

  .notice {
    color: #555;
  }

  .error {
    color: #c0392b;
    font-size: 0.9rem;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.5rem;
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
  }

  button.danger {
    background: #c0392b;
    color: white;
    border-color: #c0392b;
    margin-right: auto;
  }
</style>
