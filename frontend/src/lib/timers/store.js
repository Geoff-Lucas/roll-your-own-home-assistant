import { derived, writable } from 'svelte/store'
import { createTimer, deleteTimer, getTimers, timerAction } from '../api.js'
import { wake } from '../ambient/idle.js'

const POLL_MS = 1000
const TICK_MS = 250

// What the server last told us, and when. Between polls the countdowns are
// advanced locally from that moment, so the display moves smoothly without a
// request per frame — and never depends on the browser's clock matching the
// server's (the server sends "seconds left", not timestamps).
const items = writable([])
const receivedAt = writable(Date.now())
const clock = writable(Date.now())

function advance(item, secondsSinceReceipt) {
  if (item.kind === 'stopwatch') {
    return item.state === 'running'
      ? { ...item, elapsed_seconds: item.elapsed_seconds + secondsSinceReceipt }
      : item
  }
  if (item.state === 'running' && item.remaining_seconds != null) {
    return { ...item, remaining_seconds: Math.max(0, item.remaining_seconds - secondsSinceReceipt) }
  }
  return item
}

/** Every timer/alarm/stopwatch, with live-ticking values. */
export const timers = derived([items, receivedAt, clock], ([$items, $receivedAt, $clock]) =>
  $items.map((item) => advance(item, ($clock - $receivedAt) / 1000)),
)

export const ringing = derived(timers, ($timers) => $timers.filter((item) => item.state === 'ringing'))

let knownRinging = new Set()

function apply(state) {
  items.set(state.items)
  receivedAt.set(Date.now())
  const nowRinging = new Set(state.items.filter((item) => item.state === 'ringing').map((item) => item.id))
  // Something newly went off: leave the photo carousel so the alert is seen.
  if ([...nowRinging].some((id) => !knownRinging.has(id))) wake()
  knownRinging = nowRinging
}

export async function refresh() {
  try {
    apply(await getTimers())
  } catch {
    // A missed poll isn't worth surfacing; the next one catches up.
  }
}

let pollTimer
let tickTimer

export function startTimers() {
  refresh()
  pollTimer = setInterval(refresh, POLL_MS)
  tickTimer = setInterval(() => clock.set(Date.now()), TICK_MS)
  return () => {
    clearInterval(pollTimer)
    clearInterval(tickTimer)
  }
}

// --- actions: each returns once the server has answered, and shows its result ---

export async function create(payload) {
  const created = await createTimer(payload)
  apply({ items: created.items })
  return created
}

export async function act(id, action, body) {
  apply(await timerAction(id, action, body))
}

export async function remove(id) {
  await deleteTimer(id)
  await refresh()
}

// --- formatting ---

const pad = (n) => String(n).padStart(2, '0')

/** 8:41, or 1:05:09 once past an hour. Countdowns round up so "0:01" shows until it actually goes off. */
export function formatClock(seconds, { countdown = true } = {}) {
  const whole = Math.max(0, countdown ? Math.ceil(seconds) : Math.floor(seconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** "07:30" -> "7:30 AM" */
export function formatAlarmTime(alarmTime) {
  const [h, m] = alarmTime.split(':').map(Number)
  return `${h % 12 || 12}:${pad(m)} ${h < 12 ? 'AM' : 'PM'}`
}

const REPEAT_LABELS = { none: '', daily: 'every day', weekdays: 'weekdays' }

export function itemName(item) {
  if (item.label) return item.label
  if (item.kind === 'alarm') return `Alarm ${formatAlarmTime(item.alarm_time)}`
  return item.kind === 'stopwatch' ? 'Stopwatch' : 'Timer'
}

export function repeatLabel(item) {
  return REPEAT_LABELS[item.repeat] ?? ''
}

export const ICONS = { timer: '⏱', alarm: '⏰', stopwatch: '⏲' }
