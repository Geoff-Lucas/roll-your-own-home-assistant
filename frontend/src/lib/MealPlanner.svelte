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

  /* One row a day, top to bottom: the day, then the meal across the rest of the row.
     (Seven narrow columns cut names off: "Weeknight chicken fajitas".) */
  .days {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    flex: 1;
    min-height: 0;
  }

  .days li {
    flex: 1;
    display: flex;
    align-items: stretch;
    gap: 0.75rem;
    min-width: 0;
    min-height: 0;
  }

  .day-label {
    flex: 0 0 3.25rem;
    align-self: center;
    font-size: 1.15rem;
    font-weight: 600;
    opacity: 0.7;
  }

  .meal {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    border: 1px solid #ddd;
    border-radius: 0.4rem;
    background: #fafafa;
    cursor: pointer;
    padding: 0.3rem 0.75rem;
    overflow: hidden;
    text-align: left;
  }

  .meal img {
    flex: 0 0 auto;
    width: 4.5rem;
    height: 100%;
    object-fit: cover;
    border-radius: 0.3rem;
  }

  .meal-title {
    font-size: 1.2rem;
    line-height: 1.2;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .meal.empty {
    color: #999;
    font-size: 1.1rem;
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
