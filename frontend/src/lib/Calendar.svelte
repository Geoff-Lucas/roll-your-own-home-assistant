<script>
  import { onMount, onDestroy } from 'svelte'
  import { Calendar } from '@fullcalendar/core'
  import dayGridPlugin from '@fullcalendar/daygrid'
  import timeGridPlugin from '@fullcalendar/timegrid'
  import listPlugin from '@fullcalendar/list'
  import interactionPlugin from '@fullcalendar/interaction'
  import { createEvent, deleteEvent, getEvents, updateEvent } from './api.js'
  import EventModal from './EventModal.svelte'

  // FullCalendar has no official Svelte binding — this wraps the vanilla
  // JS Calendar class directly onto a DOM node, per FullCalendar's own
  // documented approach for frameworks without an adapter.
  let { accounts } = $props()

  const REFRESH_INTERVAL_MS = 60_000 // picks up sync-worker updates in the background

  let calendarEl
  let calendar
  let refreshTimer
  let resizeObserver

  let modalOpen = $state(false)
  let modalMode = $state('create')
  let modalInitial = $state(null)
  let editingEventId = null

  function accountColor(accountId) {
    return accounts.find((a) => a.id === accountId)?.color ?? '#888888'
  }

  function toFullCalendarEvent(row) {
    return {
      id: String(row.id),
      title: row.title,
      start: row.all_day ? row.start_date : row.start_time,
      end: row.all_day ? row.end_date : row.end_time,
      allDay: row.all_day,
      backgroundColor: accountColor(row.account_id),
      borderColor: accountColor(row.account_id),
      extendedProps: {
        location: row.location,
        description: row.description,
        accountId: row.account_id,
        rrule: row.rrule,
        reminderLeadDays: row.reminder_lead_days,
        reminderText: row.reminder_text,
      },
    }
  }

  async function fetchEvents(fetchInfo, successCallback, failureCallback) {
    try {
      const rows = await getEvents(fetchInfo.startStr, fetchInfo.endStr)
      successCallback(rows.map(toFullCalendarEvent))
    } catch (err) {
      failureCallback(err)
    }
  }

  // Deliberately naive about timezones, matching EventModal: these read the
  // *local* wall-clock components of the Date FullCalendar hands back, with
  // no UTC conversion, since the backend's naive-but-UTC convention treats
  // whatever string is typed as-is. Fine for a single-timezone household.
  function pad(n) {
    return String(n).padStart(2, '0')
  }
  function formatDateInput(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  }
  function formatDateTimeInput(date) {
    return `${formatDateInput(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
  }

  function handleDateClick(info) {
    let initial
    if (info.allDay) {
      const end = new Date(info.date)
      end.setDate(end.getDate() + 1)
      initial = { allDay: true, startValue: formatDateInput(info.date), endValue: formatDateInput(end) }
    } else {
      const end = new Date(info.date)
      end.setHours(end.getHours() + 1)
      initial = { allDay: false, startValue: formatDateTimeInput(info.date), endValue: formatDateTimeInput(end) }
    }
    modalInitial = initial
    modalMode = 'create'
    editingEventId = null
    modalOpen = true
  }

  function handleEventClick(info) {
    const event = info.event
    const allDay = event.allDay
    const end = event.end ?? event.start
    modalInitial = {
      title: event.title,
      accountId: event.extendedProps.accountId,
      rrule: event.extendedProps.rrule,
      reminderLeadDays: event.extendedProps.reminderLeadDays,
      reminderText: event.extendedProps.reminderText,
      allDay,
      startValue: allDay ? formatDateInput(event.start) : formatDateTimeInput(event.start),
      endValue: allDay ? formatDateInput(end) : formatDateTimeInput(end),
    }
    modalMode = 'edit'
    editingEventId = event.id
    modalOpen = true
  }

  async function handleSave(payload) {
    if (modalMode === 'edit') {
      await updateEvent(editingEventId, payload)
    } else {
      await createEvent(payload)
    }
    modalOpen = false
    calendar.refetchEvents()
  }

  async function handleDelete() {
    await deleteEvent(editingEventId)
    modalOpen = false
    calendar.refetchEvents()
  }

  function handleClose() {
    modalOpen = false
  }

  onMount(() => {
    calendar = new Calendar(calendarEl, {
      plugins: [dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin],
      initialView: 'dayGridMonth',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,listWeek',
      },
      height: '100%',
      // Fit all week rows into the available height (no inner scrollbar) and
      // collapse a busy day's overflow into a "+N more" link instead of growing its row.
      expandRows: true,
      dayMaxEvents: true,
      events: fetchEvents,
      dateClick: handleDateClick,
      eventClick: handleEventClick,
    })
    calendar.render()

    // FullCalendar only re-measures on window resize, but this container also
    // changes size when the page header reflows (e.g. it wraps once accounts
    // load, depending on the platform's font) — without this the calendar
    // keeps its stale first-render height and grows an inner scrollbar.
    resizeObserver = new ResizeObserver(() => calendar.updateSize())
    resizeObserver.observe(calendarEl)

    refreshTimer = setInterval(() => calendar.refetchEvents(), REFRESH_INTERVAL_MS)
  })

  onDestroy(() => {
    resizeObserver?.disconnect()
    clearInterval(refreshTimer)
    calendar?.destroy()
  })
</script>

<div class="calendar-container" bind:this={calendarEl}></div>

<EventModal
  open={modalOpen}
  mode={modalMode}
  {accounts}
  initial={modalInitial}
  onSave={handleSave}
  onDelete={handleDelete}
  onClose={handleClose}
/>

<style>
  .calendar-container {
    width: 100%;
    height: 100%;
  }
</style>
