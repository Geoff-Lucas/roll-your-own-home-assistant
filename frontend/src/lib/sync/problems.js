// Wording for a calendar that isn't syncing (the server decides which ones
// count, and when: backend app/sync/status.py).

/** "10 minutes", "3 hours", "2 days": how long it has been failing. */
export function howLong(sinceIso, now = Date.now()) {
  const minutes = Math.max(0, Math.round((now - Date.parse(sinceIso)) / 60000))
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'}`
  return `${Math.round(hours / 24)} days`
}

const WHAT = {
  relink: "Google needs you to sign in again (it ended the calendar's sign-in).",
  password: 'The calendar server turned down its password.',
  unreachable: "The calendar server can't be reached. It will keep trying.",
}

export function describeProblem(problem, now = Date.now()) {
  // Since the last good sync if known (it outlives restarts); otherwise since failing began.
  const since = problem.last_updated ?? problem.failing_since
  return {
    title: `${problem.display_name} hasn't updated for ${howLong(since, now)}`,
    detail: WHAT[problem.kind] ?? 'Syncing keeps failing.',
    fix: problem.relink_url,
    stale: 'What the calendar shows may be out of date until then.',
  }
}

/** The chip in the header: short, since the details are a tap away. */
export function chipText(problems) {
  if (problems.length === 1) return `⚠️ ${problems[0].display_name} isn't syncing`
  return `⚠️ ${problems.length} calendars aren't syncing`
}
