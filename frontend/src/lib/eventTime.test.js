import { beforeAll, describe, expect, it } from 'vitest'
import { formatDateInput, formatDateTimeInput, localInputToUtc } from './eventTime.js'

// The household's clock, whatever machine the tests run on.
beforeAll(() => {
  process.env.TZ = 'America/New_York'
})

describe('what the page shows', () => {
  it('reads an instant from the API as the local wall clock', () => {
    // 13:00 UTC is 9 AM Eastern in October (EDT, UTC-4): the bug showed it as 1 PM.
    const shown = new Date('2026-10-01T13:00:00Z')

    expect(formatDateTimeInput(shown)).toBe('2026-10-01T09:00')
  })

  it('follows daylight saving: the same 9 AM is 14:00 UTC in winter', () => {
    expect(formatDateTimeInput(new Date('2026-01-15T14:00:00Z'))).toBe('2026-01-15T09:00')
  })

  it('takes the local day, not the UTC one, late in the evening', () => {
    // 8 PM Eastern on the 1st is already the 2nd in UTC.
    expect(formatDateInput(new Date('2026-10-02T00:00:00Z'))).toBe('2026-10-01')
  })
})

describe('what the form sends', () => {
  it('turns local wall-clock digits into the right UTC instant', () => {
    expect(localInputToUtc('2026-10-01T09:00')).toBe('2026-10-01T13:00:00.000Z')
    expect(localInputToUtc('2026-01-15T09:00')).toBe('2026-01-15T14:00:00.000Z')
  })

  it('round-trips: what was shown is what gets saved back', () => {
    const fromServer = '2026-10-01T13:00:00.000Z'

    expect(localInputToUtc(formatDateTimeInput(new Date(fromServer)))).toBe(fromServer)
  })

  it('says what is missing rather than failing obscurely', () => {
    expect(() => localInputToUtc('')).toThrow('Pick a start and end time.')
    expect(() => localInputToUtc('not a time')).toThrow('Pick a start and end time.')
  })
})
