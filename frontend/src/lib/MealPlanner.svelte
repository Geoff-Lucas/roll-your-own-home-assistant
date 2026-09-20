<script>
  import { onMount } from 'svelte'
  import { getMealPlan, getRecipes, setMealPlan } from './api.js'

  let entries = $state([])
  let recipes = $state([])
  let error = $state(null)
  let pickerDate = $state(null) // the plan_date currently choosing a recipe for

  async function load() {
    try {
      entries = await getMealPlan()
      error = null
    } catch (err) {
      error = err.message
    }
  }

  async function loadRecipes() {
    try {
      recipes = await getRecipes()
    } catch {
      recipes = []
    }
  }

  function dayLabel(dateStr) {
    return new Date(`${dateStr}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' })
  }

  async function assign(planDate, recipeId) {
    try {
      const updated = await setMealPlan(planDate, recipeId)
      entries = entries.map((e) => (e.plan_date === planDate ? updated : e))
    } catch (err) {
      error = err.message
    }
    pickerDate = null
  }

  onMount(() => {
    load()
    loadRecipes()
  })
</script>

<div class="panel">
  <h3>This week's meals</h3>
  {#if error}
    <p class="error">{error}</p>
  {/if}
  <ul class="days">
    {#each entries as entry (entry.plan_date)}
      <li>
        <span class="day-label">{dayLabel(entry.plan_date)}</span>
        {#if entry.recipe_id}
          <button type="button" class="meal" onclick={() => (pickerDate = entry.plan_date)}>
            {#if entry.recipe_image}
              <img src={entry.recipe_image} alt="" />
            {/if}
            <span class="meal-title">{entry.recipe_title}</span>
          </button>
        {:else}
          <button type="button" class="meal empty" onclick={() => (pickerDate = entry.plan_date)}>+ Add meal</button>
        {/if}
      </li>
    {/each}
  </ul>
</div>

{#if pickerDate}
  <div class="overlay" role="presentation" onclick={() => (pickerDate = null)}>
    <div class="modal" role="dialog" aria-modal="true" onclick={(e) => e.stopPropagation()}>
      <h3>Pick a meal for {dayLabel(pickerDate)}</h3>
      <button type="button" class="clear" onclick={() => assign(pickerDate, null)}>Clear this day</button>
      {#if recipes.length === 0}
        <p class="empty">No saved recipes yet — add some in the Recipes tab first.</p>
      {:else}
        <ul class="recipe-options">
          {#each recipes as recipe (recipe.id)}
            <li>
              <button type="button" onclick={() => assign(pickerDate, recipe.id)}>{recipe.title}</button>
            </li>
          {/each}
        </ul>
      {/if}
      <button type="button" class="close" onclick={() => (pickerDate = null)}>Cancel</button>
    </div>
  </div>
{/if}

<style>
  .panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    background: white;
    border-radius: 0.6rem;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    padding: 0.75rem 1rem;
    overflow: hidden;
  }

  h3 {
    margin: 0 0 0.5rem;
    flex-shrink: 0;
  }

  .days {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    gap: 0.5rem;
    flex: 1;
    min-height: 0;
  }

  .days li {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
  }

  .day-label {
    font-size: 1.05rem;
    font-weight: 600;
    opacity: 0.7;
  }

  .meal {
    flex: 1;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    border: 1px solid #ddd;
    border-radius: 0.4rem;
    background: #fafafa;
    cursor: pointer;
    padding: 0.3rem;
    overflow: hidden;
  }

  .meal img {
    width: 100%;
    height: 8rem;
    object-fit: cover;
    border-radius: 0.3rem;
  }

  .meal-title {
    font-size: 1rem;
    text-align: center;
    line-height: 1.15;
  }

  .meal.empty {
    color: #999;
    font-size: 1rem;
  }

  .error {
    color: #c0392b;
  }

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
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(90vw, 24rem);
    max-height: 80vh;
    overflow-y: auto;
  }

  .modal h3 {
    margin-top: 0;
  }

  .recipe-options {
    list-style: none;
    margin: 0.5rem 0;
    padding: 0;
  }

  .recipe-options button {
    width: 100%;
    text-align: left;
    padding: 0.5rem;
    border: none;
    border-bottom: 1px solid #eee;
    background: none;
    cursor: pointer;
    font-size: 1rem;
  }

  .clear {
    width: 100%;
    padding: 0.4rem;
    margin-bottom: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
    background: #f5f5f5;
    cursor: pointer;
  }

  .close {
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
    background: #f2f2f2;
    cursor: pointer;
  }
</style>
