<script>
  import { onMount } from 'svelte'
  import { addShoppingItem, getShoppingList, removeShoppingItem, setShoppingChecked } from '../api.js'
  import { vkbd } from '../keyboard/vkbd.js'
  import { ordered, summary } from './order.js'

  // The week's shopping list, built by the server from the meal plan: what's needed for
  // today's dinner through Saturday, the same ingredient across meals on one line. Tap a
  // line to tick it off (kept for the week); anything can also be added by hand.
  let { onClose } = $props()

  let list = $state(null)
  let error = $state(null)
  let newItem = $state('')

  const items = $derived(list ? ordered(list.items) : [])

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

    <button type="button" class="close" onclick={onClose}>Close</button>
  </div>
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

  .close {
    margin-top: 0.9rem;
    padding: 0.7rem;
    font-size: 1.05rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
    background: #f2f2f2;
    cursor: pointer;
  }

  .error {
    color: #c0392b;
    margin: 0 0 0.5rem;
  }
</style>
