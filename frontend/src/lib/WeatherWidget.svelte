<script>
  import { onDestroy, onMount } from 'svelte'
  import { getWeather } from './api.js'

  // Refetch on a much shorter cycle than the backend's own refresh
  // (app/weather.py polls Open-Meteo every 30 min by default) — this just
  // picks up whatever the backend already has cached, it's not hitting the
  // provider itself.
  const REFRESH_INTERVAL_MS = 5 * 60_000

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
  let refreshTimer

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

  onMount(() => {
    load()
    refreshTimer = setInterval(load, REFRESH_INTERVAL_MS)
  })

  onDestroy(() => clearInterval(refreshTimer))
</script>

<div class="weather">
  {#if weather}
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
  {:else if error}
    <span class="error">Weather unavailable</span>
  {/if}
</div>

<style>
  .weather {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    font-size: 1rem;
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
