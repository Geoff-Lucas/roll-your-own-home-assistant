<script>
  import { onMount } from 'svelte'
  import { addShoppingItem, getShoppingList, getShoppingShare, removeShoppingItem, setShoppingChecked } from '../api.js'
  import { vkbd } from '../keyboard/vkbd.js'
  import { ordered, summary } from './order.js'

  // The week's shopping list, built by the server from the meal plan: what's needed for
  // today's dinner through Saturday, the same ingredient across meals on one line. Tap a
  // line to tick it off (kept for the week); anything can also be added by hand.
  let { onClose } = $props()

  let list = $state(null)
  let error = $state(null)
  let newItem = $state('')
  let sharing = $state(null) // the QR code for the phone, while it's on screen

  const items = $derived(list ? ordered(list.items) : [])

  // A QR code that opens an email with what's left to buy; scanning it with a phone's
  // camera is all it takes, and nothing is sent from here.
  async function share() {
    try {
      sharing = await getShoppingShare()
      error = null
    } catch (err) {
      error = err.message
    }
  }

  async function load() {
    try {
      list = await getShoppingList()
      error = null
    } catch (err) {
      error = err.message
    }
  }

  async function toggle(item) {
    const checked = !item.checked
    item.checked = checked // straight away; put back below if the server says no
    try {
      await setShoppingChecked(item.key, checked)
    } catch (err) {
      item.checked = !checked
      error = err.message
    }
  }

  async function add() {
    const name = newItem.trim()
    if (!name) return
    try {
      const added = await addShoppingItem(name)
      list.items.push(added)
      newItem = ''
      error = null
    } catch (err) {
      error = err.message
    }
  }

  async function remove(item) {
    try {
      await removeShoppingItem(item.key)
      list.items = list.items.filter((other) => other.key !== item.key)
    } catch (err) {
      error = err.message
    }
  }

  onMount(load)
</script>

<div class="overlay" role="presentation" onclick={onClose}>
  {#if sharing}
    <div class="modal wide" role="dialog" aria-modal="true" aria-label="Send to phone" onclick={(e) => e.stopPropagation()}>
      <h3>Send to phone</h3>
      {#if sharing.qr}
        <p class="summary">Point your phone's camera at this. It opens an email with the list, ready to send.</p>
        <img class="qr" src={sharing.qr} alt="A QR code that opens an email with the shopping list" />
        {#if sharing.left_out > 0}
          <p class="note">
            The list was too long for one code: the email has the first {sharing.included} items and says {sharing.left_out} more
            are on the kiosk.
          </p>
        {/if}
      {:else}
        <p class="summary">There's nothing left to buy, so there's nothing to send.</p>
      {/if}
      <button type="button" class="close" onclick={() => (sharing = null)}>Back to the list</button>
    </div>
  {:else}
  <div class="modal" role="dialog" aria-modal="true" aria-label="Shopping list" onclick={(e) => e.stopPropagation()}>
    <h3>Shopping list</h3>
    {#if list}
      <p class="summary">{summary(list)}</p>
    {/if}

    <form class="add" onsubmit={(e) => { e.preventDefault(); add() }}>
      <input type="text" placeholder="Add something…" bind:value={newItem} use:vkbd />
      <button type="submit" disabled={!newItem.trim()}>Add</button>
    </form>

    {#if error}
      <p class="error">{error}</p>
    {/if}

    <ul>
      {#each items as item (item.key)}
        <li class:done={item.checked}>
          <button type="button" class="row" aria-pressed={item.checked} onclick={() => toggle(item)}>
            <span class="tick" aria-hidden="true">{item.checked ? '✓' : ''}</span>
            <span class="text">
              <span class="line">
                <span class="name">{item.name}</span>
                {#if item.quantity}<span class="quantity">{item.quantity}</span>{/if}
              </span>
              {#if item.recipes.length}
                <span class="for">for {item.recipes.join(', ')}</span>
              {/if}
            </span>
          </button>
          {#if item.manual}
            <button type="button" class="remove" aria-label="Remove {item.name}" onclick={() => remove(item)}>✕</button>
          {/if}
        </li>
      {/each}
    </ul>

    <div class="footer">
      <button type="button" class="close" onclick={share}>📱 Send to phone</button>
      <button type="button" class="close" onclick={onClose}>Close</button>
    </div>
  </div>
  {/if}
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    display: flex;
    flex-direction: column;
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(92vw, 44rem);
    max-height: 70vh; /* leaves the on-screen keyboard room when adding something */
  }

  h3 {
    margin: 0;
    font-size: 1.5rem;
  }

  .summary {
    margin: 0.2rem 0 0.9rem;
    opacity: 0.65;
    font-size: 1.05rem;
  }

  .add {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .add input {
    flex: 1;
    min-width: 0;
    padding: 0.7rem 0.8rem;
    font-size: 1.1rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
  }

  .add button {
    padding: 0 1.4rem;
    font-size: 1.05rem;
    border: none;
    border-radius: 0.4rem;
    background: #2563eb;
    color: white;
    cursor: pointer;
  }

  .add button:disabled {
    background: #b9c6e4;
    cursor: default;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }

  li {
    display: flex;
    align-items: center;
    border-bottom: 1px solid #eee;
  }

  .row {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.7rem 0.25rem;
    border: none;
    background: none;
    text-align: left;
    cursor: pointer;
    font: inherit;
    color: inherit;
  }

  .tick {
    flex: 0 0 auto;
    width: 2.4rem;
    height: 2.4rem;
    border: 2px solid #999;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.3rem;
    color: white;
  }

  .done .tick {
    background: #2e9e5b;
    border-color: #2e9e5b;
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.6rem;
  }

  .name {
    font-size: 1.25rem;
    font-weight: 600;
  }

  .name::first-letter {
    text-transform: uppercase;
  }

  .quantity {
    font-size: 1.15rem;
    color: #b8860b;
    font-weight: 600;
  }

  .for {
    font-size: 0.95rem;
    opacity: 0.6;
  }

  .done .name,
  .done .quantity {
    text-decoration: line-through;
    opacity: 0.5;
  }

  .done .for {
    opacity: 0.35;
  }

  .remove {
    flex: 0 0 auto;
    width: 2.75rem;
    height: 2.75rem;
    border: 1px solid #ccc;
    border-radius: 50%;
    background: #f5f5f5;
    cursor: pointer;
    font-size: 1.05rem;
  }

  .footer {
    display: flex;
    gap: 0.75rem;
    margin-top: 0.9rem;
  }

  .footer .close {
    flex: 1;
    margin-top: 0;
  }

  .close {
    margin-top: 0.9rem;
    padding: 0.7rem;
    font-size: 1.05rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
    background: #f2f2f2;
    cursor: pointer;
  }

  /* The code is dense on a full list, so it's drawn as big as the screen allows. */
  .modal.wide {
    width: min(94vw, 64rem);
    max-height: 90vh;
    align-items: center;
    text-align: center;
  }

  .modal.wide .close {
    align-self: stretch;
  }

  .qr {
    width: min(100%, 60vh);
    aspect-ratio: 1;
    margin: 0.25rem 0;
    image-rendering: crisp-edges;
  }

  .note {
    margin: 0.4rem 0 0;
    opacity: 0.75;
  }

  .error {
    color: #c0392b;
    margin: 0 0 0.5rem;
  }
</style>
