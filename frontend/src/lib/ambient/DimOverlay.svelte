<script>
  import { onDestroy, onMount } from 'svelte'
  import { getAmbientStatus } from '../api.js'

  const CHECK_INTERVAL_MS = 60_000 // dim state only changes on the hour boundary, no need to poll fast

  let isDim = $state(false)
  let timer

  async function check() {
    try {
      isDim = (await getAmbientStatus()).is_dim_time
    } catch {
      // leave whatever it was — a transient failure shouldn't flip the display state
    }
  }

  onMount(() => {
    check()
    timer = setInterval(check, CHECK_INTERVAL_MS)
  })

  onDestroy(() => clearInterval(timer))
</script>

{#if isDim}
  <!-- CSS-only dimming — reduces apparent brightness of the page content.
       This is NOT real backlight/brightness control (that needs an OS-level
       mechanism like xrandr/vcgencmd/ddcutil on the Pi itself, which can't
       be done from a browser page); it's a first pass, good enough to dim
       the visual glare overnight. Revisit with real hardware dimming later. -->
  <div class="dim-overlay"></div>
{/if}

<style>
  .dim-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    pointer-events: none;
    z-index: 1500;
  }
</style>
