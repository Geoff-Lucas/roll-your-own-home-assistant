<script>
  import { onMount } from 'svelte'
  import { vkbd } from './keyboard/vkbd.js'
  import { currentPerson } from './currentPerson.js'
  import { favoriteRecipe, getFavoriteRecipeIds, getRecipes, importRecipe, unfavoriteRecipe } from './api.js'
  import RecipeDetailModal from './RecipeDetailModal.svelte'

  let recipes = $state([])
  let favoriteIds = $state(new Set())
  let importUrl = $state('')
  let importing = $state(false)
  let importError = $state(null)
  let loadError = $state(null)
  let selectedRecipe = $state(null)

  async function loadRecipes() {
    try {
      recipes = await getRecipes()
      loadError = null
    } catch (err) {
      loadError = err.message
    }
  }

  async function loadFavorites() {
    if (!$currentPerson) {
      favoriteIds = new Set()
      return
    }
    try {
      favoriteIds = new Set(await getFavoriteRecipeIds($currentPerson))
    } catch {
      favoriteIds = new Set()
    }
  }

  onMount(loadRecipes)

  $effect(() => {
    $currentPerson
    loadFavorites()
  })

  async function handleImport() {
    const url = importUrl.trim()
    if (!url) return
    importing = true
    importError = null
    try {
      const recipe = await importRecipe(url)
      recipes = [recipe, ...recipes]
      importUrl = ''
    } catch (err) {
      importError = err.message
    } finally {
      importing = false
    }
  }

  async function toggleFavorite(recipe) {
    if (!$currentPerson) return
    try {
      if (favoriteIds.has(recipe.id)) {
        await unfavoriteRecipe(recipe.id, $currentPerson)
      } else {
        await favoriteRecipe(recipe.id, $currentPerson)
        await loadRecipes() // picks up image_path if this was the recipe's first-ever favorite
      }
      await loadFavorites()
    } catch (err) {
      loadError = err.message
    }
  }

  function thumbnail(recipe) {
    return recipe.image_path ?? recipe.source_image_url ?? null
  }
</script>

<div class="recipes">
  <div class="import-box">
    <input
      type="text"
      placeholder="Paste a recipe URL to import…"
      bind:value={importUrl}
      use:vkbd
      onkeydown={(e) => e.key === 'Enter' && handleImport()}
    />
    <button type="button" onclick={handleImport} disabled={importing}>
      {importing ? 'Importing…' : 'Import'}
    </button>
  </div>

  {#if importError}
    <p class="error">{importError}</p>
  {/if}
  {#if loadError}
    <p class="error">{loadError}</p>
  {/if}

  <div class="grid">
    {#each recipes as recipe (recipe.id)}
      <div class="card">
        <button type="button" class="card-main" onclick={() => (selectedRecipe = recipe)}>
          <div class="thumb">
            {#if thumbnail(recipe)}
              <img src={thumbnail(recipe)} alt="" />
            {:else}
              <div class="thumb-placeholder">🍽️</div>
            {/if}
          </div>
          <div class="card-body">
            <h3>{recipe.title}</h3>
            <div class="badges">
              {#each recipe.dietary_tags as tag (tag)}
                <span class="badge">{tag}</span>
              {/each}
            </div>
          </div>
        </button>
        <button
          type="button"
          class="favorite-star"
          class:active={favoriteIds.has(recipe.id)}
          onclick={() => toggleFavorite(recipe)}
          aria-label={favoriteIds.has(recipe.id) ? 'Unfavorite' : 'Favorite'}
        >
          {favoriteIds.has(recipe.id) ? '★' : '☆'}
        </button>
      </div>
    {/each}
  </div>
</div>

<RecipeDetailModal recipe={selectedRecipe} onClose={() => (selectedRecipe = null)} />

<style>
  .recipes {
    height: 100%;
    overflow-y: auto;
    padding: 0 1rem 1rem;
  }

  .import-box {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  .import-box input {
    flex: 1;
    font-size: 1rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
  }

  .import-box button {
    font-size: 1rem;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #2563eb;
    background: #2563eb;
    color: white;
  }

  .error {
    color: #c0392b;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
    gap: 1rem;
  }

  .card {
    position: relative;
    border-radius: 0.6rem;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
    background: white;
  }

  .card-main {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    color: inherit;
    font: inherit;
  }

  .thumb {
    aspect-ratio: 4 / 3;
    background: #eee;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }

  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .thumb-placeholder {
    font-size: 2.5rem;
  }

  .card-body {
    padding: 0.6rem 0.75rem;
  }

  .card-body h3 {
    margin: 0 0 0.3rem;
    font-size: 1.05rem;
  }

  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }

  .badge {
    background: #e3f2e1;
    color: #2c5c2a;
    border-radius: 1rem;
    padding: 0.1rem 0.6rem;
    font-size: 0.75rem;
  }

  .favorite-star {
    position: absolute;
    top: 0.4rem;
    right: 0.4rem;
    background: rgba(255, 255, 255, 0.85);
    border: none;
    border-radius: 50%;
    width: 2.2rem;
    height: 2.2rem;
    font-size: 1.3rem;
    line-height: 1;
    cursor: pointer;
    color: #999;
  }

  .favorite-star.active {
    color: #e0a415;
  }
</style>
