<script>
  let { recipe, onClose, onEdit } = $props()

  // Imported recipes link back to their page; a typed one may not have one.
  const isLink = (url) => /^https?:\/\//i.test(url ?? '')
</script>

{#if recipe}
  <div class="overlay" role="presentation" onclick={onClose}>
    <div class="modal" role="dialog" aria-modal="true" onclick={(e) => e.stopPropagation()}>
      <button type="button" class="close" onclick={onClose} aria-label="Close">✕</button>

      {#if recipe.image_path || recipe.source_image_url}
        <img class="hero" src={recipe.image_path ?? recipe.source_image_url} alt="" />
      {/if}

      <h2>{recipe.title}</h2>

      <div class="meta">
        {#if recipe.prep_time_minutes}<span>Prep {recipe.prep_time_minutes}m</span>{/if}
        {#if recipe.cook_time_minutes}<span>Cook {recipe.cook_time_minutes}m</span>{/if}
        {#if recipe.servings}<span>Serves {recipe.servings}</span>{/if}
      </div>

      {#if recipe.dietary_tags.length || recipe.allergens.length}
        <div class="badges">
          {#each recipe.dietary_tags as tag (tag)}
            <span class="badge">{tag}</span>
          {/each}
          {#each recipe.allergens as allergen (allergen)}
            <span class="badge allergen">contains {allergen}</span>
          {/each}
        </div>
      {/if}

      <h3>Ingredients</h3>
      <ul>
        {#each recipe.ingredients as ingredient, i (i)}
          <li>{ingredient.raw_text}</li>
        {/each}
      </ul>

      <h3>Steps</h3>
      <ol>
        {#each recipe.steps as step, i (i)}
          <li>{step}</li>
        {/each}
      </ol>

      {#if isLink(recipe.source_url)}
        <p class="source"><a href={recipe.source_url} target="_blank" rel="noreferrer">View original recipe</a></p>
      {/if}

      {#if onEdit}
        <div class="actions">
          <button type="button" onclick={() => onEdit(recipe)}>✏️ Edit</button>
        </div>
      {/if}
    </div>
  </div>
{/if}

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
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(90vw, 34rem);
    max-height: 85vh;
    overflow-y: auto;
    position: relative;
  }

  .close {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    background: none;
    border: none;
    font-size: 1.3rem;
    cursor: pointer;
    line-height: 1;
    padding: 0.25rem;
  }

  .hero {
    width: 100%;
    max-height: 14rem;
    object-fit: cover;
    border-radius: 0.5rem;
    margin-bottom: 0.75rem;
  }

  h2 {
    margin: 0 0 0.5rem;
  }

  .meta {
    display: flex;
    gap: 1rem;
    font-size: 0.95rem;
    opacity: 0.8;
    margin-bottom: 0.5rem;
  }

  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
  }

  .badge {
    background: #e3f2e1;
    color: #2c5c2a;
    border-radius: 1rem;
    padding: 0.15rem 0.7rem;
    font-size: 0.85rem;
  }

  .badge.allergen {
    background: #fdeaea;
    color: #a12626;
  }

  ul,
  ol {
    padding-left: 1.25rem;
    margin: 0.25rem 0 1rem;
  }

  li {
    margin-bottom: 0.35rem;
  }

  .source {
    font-size: 0.9rem;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
  }

  .actions button {
    font-size: 1rem;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
  }
</style>
