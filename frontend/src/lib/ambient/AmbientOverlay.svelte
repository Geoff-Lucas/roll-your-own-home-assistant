<script>
  import { onDestroy, onMount } from 'svelte'
  import { getAmbientPhotos, getAmbientStatus } from '../api.js'
  import { wake } from './idle.js'

  const PHOTO_INTERVAL_MS = 15_000
  const MOTION_POLL_MS = 5_000

  let photos = $state([])
  let index = $state(0)
  let photoTimer
  let motionTimer

  async function loadPhotos() {
    try {
      photos = await getAmbientPhotos()
    } catch {
      photos = []
    }
  }

  async function pollMotion() {
    try {
      const status = await getAmbientStatus()
      // Motion wake returns to the dashboard, same as a touch — the
      // carousel is a screensaver, not a destination (PLAN.md Ambient mode).
      if (status.motion_detected) wake()
    } catch {
      // no motion sensor, or a transient network hiccup — just try again next poll
    }
  }

  onMount(() => {
    loadPhotos()
    photoTimer = setInterval(() => {
      if (photos.length > 0) index = (index + 1) % photos.length
    }, PHOTO_INTERVAL_MS)
    motionTimer = setInterval(pollMotion, MOTION_POLL_MS)
  })

  onDestroy(() => {
    clearInterval(photoTimer)
    clearInterval(motionTimer)
  })
</script>

<div class="ambient" onclick={wake} role="presentation">
  {#if photos.length > 0}
    {#each photos as photo, i (photo)}
      <img src={photo} alt="" class:visible={i === index} />
    {/each}
  {:else}
    <p class="empty">No ambient photos yet — drop some into the ambient_photos folder.</p>
  {/if}
</div>

<style>
  .ambient {
    position: fixed;
    inset: 0;
    background: black;
    z-index: 500;
  }

  img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
    transition: opacity 1.5s ease;
  }

  img.visible {
    opacity: 1;
  }

  .empty {
    color: #999;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-size: 1.2rem;
    padding: 2rem;
    text-align: center;
  }
</style>
