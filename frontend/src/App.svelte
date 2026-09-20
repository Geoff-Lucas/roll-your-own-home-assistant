<script>
  import { onMount } from 'svelte'
  import Calendar from './lib/Calendar.svelte'
  import RecipeList from './lib/RecipeList.svelte'
  import RemindersList from './lib/RemindersList.svelte'
  import MealPlanner from './lib/MealPlanner.svelte'
  import WeatherWidget from './lib/WeatherWidget.svelte'
  import LocationBadge from './lib/LocationBadge.svelte'
  import VirtualKeyboard from './lib/keyboard/VirtualKeyboard.svelte'
  import AmbientOverlay from './lib/ambient/AmbientOverlay.svelte'
  import DimOverlay from './lib/ambient/DimOverlay.svelte'
  import { isIdle, startIdleWatcher, configureIdleTimeout } from './lib/ambient/idle.js'
  import { currentPerson } from './lib/currentPerson.js'
  import { getAccounts, getAmbientConfig } from './lib/api.js'

  let accounts = $state([])
  let loadError = $state(null)
  let activeView = $state('calendar')

  // Household members, deduplicated — several accounts (e.g. two calendars
  // for the same person) can share a person_name.
  const people = $derived([...new Set(accounts.map((a) => a.person_name))])

  onMount(async () => {
    try {
      accounts = await getAccounts()
      if (accounts.length > 0) {
        currentPerson.set(accounts[0].person_name)
      }
    } catch (err) {
      loadError = err.message
    }

    try {
      const config = await getAmbientConfig()
      configureIdleTimeout(config.idle_timeout_seconds)
    } catch {
      configureIdleTimeout(300) // backend unreachable at startup — fall back to a sane default
    }
    startIdleWatcher()
  })
</script>

<main class="app">
  <header class="topbar">
    <div class="top-row">
      <WeatherWidget />
      <LocationBadge />
    </div>
    <div class="people-row">
      <div class="legend">
        {#each accounts as account (account.id)}
          <span class="legend-item">
            <span class="dot" style="background-color: {account.color}"></span>
            {account.person_name}
          </span>
        {/each}
        {#if loadError}
          <span class="error">Couldn't load accounts: {loadError}</span>
        {/if}
      </div>
      {#if people.length > 0}
        <label class="acting-as">
          Acting as
          <select bind:value={$currentPerson}>
            {#each people as person (person)}
              <option value={person}>{person}</option>
            {/each}
          </select>
        </label>
      {/if}
      <nav class="tabs">
        <button type="button" class:active={activeView === 'calendar'} onclick={() => (activeView = 'calendar')}>
          Calendar
        </button>
        <button type="button" class:active={activeView === 'recipes'} onclick={() => (activeView = 'recipes')}>
          Recipes
        </button>
      </nav>
    </div>
  </header>
  <section class="content-area">
    {#if activeView === 'calendar'}
      <div class="calendar-page">
        <div class="calendar-main">
          <Calendar {accounts} />
        </div>
        <div class="below-calendar">
          <RemindersList />
          <MealPlanner />
        </div>
      </div>
    {:else}
      <RecipeList />
    {/if}
  </section>
</main>

{#if $isIdle}
  <AmbientOverlay />
{/if}

<DimOverlay />

<VirtualKeyboard />

<style>
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    width: 100vw;
  }

  .topbar {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0.75rem 1.25rem;
    flex-shrink: 0;
  }

  /* Weather, then the location badge (with its own divider) on the right. */
  .top-row {
    display: flex;
    align-items: stretch;
    justify-content: space-between;
    gap: 1.25rem;
  }

  /* People color legend, the "acting as" selector right beside it, and the
     view tabs pinned to the far right (they don't fit beside the weather). */
  .people-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem 2rem;
  }

  .legend {
    display: flex;
    gap: 1.25rem;
    align-items: center;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.1rem;
  }

  .dot {
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    display: inline-block;
  }

  .error {
    color: #c0392b;
    font-size: 1rem;
  }

  .tabs {
    display: flex;
    gap: 0.5rem;
    margin-left: auto;
  }

  .tabs button {
    font-size: 1rem;
    padding: 0.4rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
    cursor: pointer;
  }

  .tabs button.active {
    background: #1f2937;
    color: white;
    border-color: #1f2937;
  }

  .acting-as {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1rem;
  }

  .acting-as select {
    font-size: 1rem;
    padding: 0.3rem 0.5rem;
  }

  .content-area {
    flex: 1;
    min-height: 0;
    padding: 0 1rem 1rem;
  }

  .calendar-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    gap: 1rem;
  }

  .calendar-main {
    flex: 1 1 auto;
    min-height: 0;
  }

  .below-calendar {
    display: flex;
    gap: 1rem;
    flex: 0 0 25vh; /* bottom quarter of the screen */
  }

  .below-calendar > :global(*) {
    flex: 1;
    min-width: 0;
  }
</style>
