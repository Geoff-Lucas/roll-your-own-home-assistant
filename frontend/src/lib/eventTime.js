// Event times. The API sends and stores real instants in UTC ("2026-10-01T13:00:00Z");
// the page shows them on the household's wall clock, which is the browser's own.
// The datetime-local inputs in the event form deal in that wall clock ("2026-10-01T09:00")
// and carry no offset, so they're converted at the two edges: read from a Date (which
// FullCalendar hands back in local time) on the way into the form, and turned into an
// instant on the way out to the API.

function pad(n) {
  return String(n).padStart(2, '0')
}

/** "2026-10-01": the local calendar day of a Date. */
export function formatDateInput(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** "2026-10-01T09:00": the local wall-clock time of a Date, as a datetime-local input wants it. */
export function formatDateTimeInput(date) {
  return `${formatDateInput(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * A datetime-local value (local wall clock) as the UTC instant to send to the API:
 * "2026-10-01T09:00" is "2026-10-01T13:00:00.000Z" in New York in October.
 */
export function localInputToUtc(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) throw new Error('Pick a start and end time.')
  return date.toISOString()
}

/** The browser's IANA time zone ("America/New_York"), sent along so the calendar copy carries it. */
export function browserTimeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}
