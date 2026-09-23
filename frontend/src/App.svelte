<script>
  import { onMount } from 'svelte'
  import Calendar from './lib/Calendar.svelte'
  import RecipeList from './lib/RecipeList.svelte'
  import RemindersList from './lib/RemindersList.svelte'
  import MealPlanner from './lib/MealPlanner.svelte'
  import WeatherWidget from './lib/WeatherWidget.svelte'
  import BrowserView from './lib/BrowserView.svelte'
  import TimerChips from './lib/timers/TimerChips.svelte'
  import VoiceButton from './lib/voice/VoiceButton.svelte'
  import VoiceOverlay from './lib/voice/VoiceOverlay.svelte'
  import { watchVoice } from './lib/voice/store.js'
  import RingingOverlay from './lib/timers/RingingOverlay.svelte'
  import { startTimers } from './lib/timers/store.js'
  import LocationBadge from './lib/LocationBadge.svelte'
  import VirtualKeyboard from './lib/keyboard/VirtualKeyboard.svelte'
  import AmbientOverlay from './lib/ambient/AmbientOverlay.svelte'
  import DimOverlay from './lib/ambient/DimOverlay.svelte'
  import { isIdle, idleSuspended, startIdleWatcher, configureIdleTimeout } from './lib/ambient/idle.js'
  import { currentPerson } from './lib/currentPerson.js'
  import { getAccounts, getAmbientConfig, hideBrowser, minimizeToDesktop } from './lib/api.js'

  let accounts = $state([])
  let loadError = $state(null)
  let activeView = $state('calendar')
  let minimizeError = $state(null)

  // Household members, deduplicated — several accounts (e.g. two calendars
  // for the same person) can share a person_name.
  const people = $derived([...new Set(accounts.map((a) => a.person_name))])

  // The Browser tab's window is a separate OS window that outlives this page:
  // after a reload it could still be sitting on top of the app, so put it away.
  $effect(() => {
    idleSuspended.set(activeView === 'browser')
  })

  onMount(async () => {
    hideBrowser().catch(() => {})
    startTimers()
    watchVoice()

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

  // Steps out to the XFCE desktop underneath (see deploy/README.md "Minimizing
  // to the desktop" for how to get back — there's no taskbar to click on a kiosk).
  // Only works on the kiosk itself (needs a display and xdotool); elsewhere the
  // backend reports 503, which is the one failure worth telling anyone about.
  async function minimizeToDesktopClicked() {
    minimizeError = null
    try {
      await minimizeToDesktop()
    } catch (err) {
      minimizeError = err.message
    }
  }
</script>

<div class="fall-background" aria-hidden="true"></div>

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
      <TimerChips />
      <VoiceButton />
      <nav class="tabs">
        <button type="button" class:active={activeView === 'calendar'} onclick={() => (activeView = 'calendar')}>
          Calendar
        </button>
        <button type="button" class:active={activeView === 'recipes'} onclick={() => (activeView = 'recipes')}>
          Recipes
        </button>
        <button type="button" class:active={activeView === 'browser'} onclick={() => (activeView = 'browser')}>
          Browser
        </button>
      </nav>
      <button type="button" class="minimize" aria-label="Minimize to the desktop" onclick={minimizeToDesktopClicked}>
        🖥️ Desktop
      </button>
      {#if minimizeError}<span class="error">{minimizeError}</span>{/if}
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
    {:else if activeView === 'recipes'}
      <RecipeList />
    {:else}
      <BrowserView onOpenRecipes={() => (activeView = 'recipes')} />
    {/if}
  </section>
</main>

{#if $isIdle}
  <AmbientOverlay />
{/if}

<DimOverlay />

<VoiceOverlay />

<RingingOverlay />

<VirtualKeyboard />

<style>
  /* A seasonal backdrop, faint enough to stay out of the way of text sitting
     directly on it (the header's weather/location, the calendar grid) — the
     cards elsewhere (recipes, reminders, meal plan) are opaque over it anyway. */
  .fall-background {
    position: fixed;
    inset: 0;
    z-index: -1;
    background: url('/fall-background.svg') center / cover no-repeat;
    opacity: 0.35;
    pointer-events: none;
  }

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

  /* Deliberately plain, not part of the tab group it sits beside — this steps
     out of the app entirely rather than switching to another view of it.
     margin-left: auto keeps it pinned to the right edge even if it wraps to
     its own line below the tabs on a narrow header (both are the same rule
     the tabs use to reach the right edge of *their* line). */
  .minimize {
    margin-left: auto;
    font-size: 1rem;
    padding: 0.4rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
    background: none;
    cursor: pointer;
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
