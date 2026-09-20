<script>
  import { onDestroy, onMount } from 'svelte'
  import { getWeather } from './api.js'
  import { locationVersion } from './weatherLocation.js'

  // Refetch on a much shorter cycle than the backend's own refresh
  // (app/weather.py polls Open-Meteo every 30 min by default) — this just
  // picks up whatever the backend already has cached, it's not hitting the
  // provider itself.
  const REFRESH_INTERVAL_MS = 5 * 60_000

  const HOURS_SHOWN = 5
  // Only call out rain when it's a real possibility — a "5%" on every hour is noise.
  const RAIN_CHANCE_SHOWN_AT = 30
  // The hourly list is cached for up to 30 min, so re-evaluate which hours are
  // still "upcoming" against the clock rather than trusting the fetch time.
  const CLOCK_TICK_MS = 60_000

  const ICONS = {
    clear: '☀️',
    'partly-cloudy': '⛅',
    cloudy: '☁️',
    fog: '🌫️',
    drizzle: '🌦️',
    rain: '🌧️',
    snow: '❄️',
    thunderstorm: '⛈️',
    unknown: '❓',
  }

  let weather = $state(null)
  let error = $state(null)
  let now = $state(Date.now())
  let refreshTimer
  let clockTimer
  let unsubscribeLocation

  // Hourly times are naive and local to the *forecast location* — which, now
  // that the location is selectable, isn't necessarily where this device is.
  // Reading them as UTC and subtracting the location's UTC offset gives the
  // real instant, so "is this hour still upcoming?" is right for any place.
  function hourInstant(timeStr) {
    return Date.parse(`${timeStr}Z`) - (weather?.utc_offset_seconds ?? 0) * 1000
  }

  const upcomingHours = $derived(
    (weather?.hourly ?? []).filter((hour) => hourInstant(hour.time) > now).slice(0, HOURS_SHOWN),
  )

  async function load() {
    try {
      weather = await getWeather()
      error = null
    } catch (err) {
      error = err.message
    }
  }

  function icon(key) {
    return ICONS[key] ?? ICONS.unknown
  }

  function formatDay(dateStr) {
    return new Date(`${dateStr}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' })
  }

  // The label should read as the location's own clock time, so format the
  // naive string as-if-UTC and display it in UTC (no zone shifting).
  function formatHour(timeStr) {
    return new Date(`${timeStr}Z`).toLocaleTimeString(undefined, { hour: 'numeric', timeZone: 'UTC' })
  }

  onMount(() => {
    load()
    refreshTimer = setInterval(load, REFRESH_INTERVAL_MS)
    clockTimer = setInterval(() => (now = Date.now()), CLOCK_TICK_MS)
    // A store subscription fires once immediately with the initial value (0);
    // only a real change (> 0) should trigger the extra refetch.
    unsubscribeLocation = locationVersion.subscribe((version) => {
      if (version > 0) load()
    })
  })

  onDestroy(() => {
    clearInterval(refreshTimer)
    clearInterval(clockTimer)
    unsubscribeLocation?.()
  })
</script>

<div class="weather">
  {#if weather}
    <div class="daily-row">
      <div class="current">
        <span class="icon">{icon(weather.current.icon)}</span>
        <span class="temp">{Math.round(weather.current.temperature)}{weather.unit}</span>
      </div>
      <div class="forecast">
        {#each weather.forecast.slice(0, 4) as day (day.date)}
          <div class="day">
            <span class="day-label">{formatDay(day.date)}</span>
            <span class="day-icon">{icon(day.icon)}</span>
            <span class="day-temps">{Math.round(day.high)}°/{Math.round(day.low)}°</span>
          </div>
        {/each}
      </div>
    </div>
    {#if upcomingHours.length > 0}
      <div class="hourly">
        {#each upcomingHours as hour (hour.time)}
          <div class="hour">
            <span class="hour-label">{formatHour(hour.time)}</span>
            <span class="hour-icon">{icon(hour.icon)}</span>
            <span class="hour-temp">{Math.round(hour.temperature)}°</span>
            <span class="hour-rain" class:hidden={!(hour.precipitation_probability >= RAIN_CHANCE_SHOWN_AT)}>
              💧{hour.precipitation_probability}%
            </span>
          </div>
        {/each}
      </div>
    {/if}
  {:else if error}
    <span class="error">Weather unavailable</span>
  {/if}
</div>

<style>
  /* Daily forecast on the left, hourly strip on the right, split by a
     vertical rule. */
  .weather {
    display: flex;
    flex-direction: row;
    align-items: stretch;
    gap: 1.25rem;
    font-size: 1rem;
  }

  .daily-row {
    display: flex;
    align-items: center;
    gap: 1.25rem;
  }

  .hourly {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding-left: 1.25rem;
    border-left: 1px solid rgba(128, 128, 128, 0.35);
  }

  .hour {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.1rem;
    min-width: 3rem;
    font-size: 0.9rem;
    opacity: 0.9;
  }

  .hour-label {
    opacity: 0.75;
  }

  .hour-icon {
    font-size: 1.2rem;
  }

  .hour-temp {
    font-weight: 600;
  }

  .hour-rain {
    font-size: 0.75rem;
    color: #2b6cb0;
  }

  /* Keep the rain line's height even when empty so hours stay aligned. */
  .hour-rain.hidden {
    visibility: hidden;
  }

  .current {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.4rem;
    font-weight: 600;
  }

  .current .icon {
    font-size: 1.9rem;
  }

  .forecast {
    display: flex;
    gap: 1rem;
  }

  .day {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    font-size: 0.95rem;
    opacity: 0.85;
  }

  .day-icon {
    font-size: 1.3rem;
  }

  .error {
    font-size: 1rem;
    opacity: 0.7;
  }
</style>
