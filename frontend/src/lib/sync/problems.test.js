import { describe, expect, it } from 'vitest'
import { chipText, describeProblem, howLong } from './problems.js'

const NOW = Date.parse('2026-09-27T18:00:00Z')
const problem = (overrides = {}) => ({
  account_id: 1,
  display_name: 'Geoff Google',
  person_name: 'Geoff',
  kind: 'relink',
  failing_since: '2026-09-27T02:23:00+00:00',
  relink_url: 'http://localhost:8000/api/google-oauth/start?account_id=1',
  ...overrides,
})

describe('how long it has been failing', () => {
  it('reads naturally at every scale', () => {
    expect(howLong('2026-09-27T17:59:00Z', NOW)).toBe('1 minute')
    expect(howLong('2026-09-27T17:35:00Z', NOW)).toBe('25 minutes')
    expect(howLong('2026-09-27T15:00:00Z', NOW)).toBe('3 hours')
    expect(howLong('2026-09-24T18:00:00Z', NOW)).toBe('3 days')
  })

  it('never goes negative if the clocks disagree a little', () => {
    expect(howLong('2026-09-27T18:01:00Z', NOW)).toBe('0 minutes')
  })
})

describe('what the warning says', () => {
  it('an expired Google sign-in offers the fix', () => {
    const shown = describeProblem(problem(), NOW)

    expect(shown.title).toBe("Geoff Google hasn't updated for 16 hours")
    expect(shown.detail).toMatch(/sign in again/)
    expect(shown.fix).toBe('http://localhost:8000/api/google-oauth/start?account_id=1')
  })

  it('counts from the last good sync when known, since failing only began at the last restart', () => {
    const shown = describeProblem(problem({ last_updated: '2026-09-26T02:18:00+00:00' }), NOW)

    expect(shown.title).toBe("Geoff Google hasn't updated for 40 hours")
  })

  it('an unreachable server just says it will keep trying', () => {
    const shown = describeProblem(problem({ kind: 'unreachable', relink_url: null }), NOW)

    expect(shown.detail).toMatch(/keep trying/)
    expect(shown.fix).toBeNull()
  })

  it('names the calendar in the header chip, or counts them', () => {
    expect(chipText([problem()])).toBe("⚠️ Geoff Google isn't syncing")
    expect(chipText([problem(), problem({ account_id: 2 })])).toBe("⚠️ 2 calendars aren't syncing")
  })
})
