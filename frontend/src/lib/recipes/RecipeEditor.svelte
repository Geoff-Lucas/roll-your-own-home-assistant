<script>
  // Typing a recipe in by hand, or fixing one (imported or typed). Saved
  // recipes are structured by the server exactly like imported ones, so they
  // go on the meal plan and can feed a shopping list the same way.
  import { untrack } from 'svelte'
  import { vkbd } from '../keyboard/vkbd.js'
  import { createRecipe, deleteRecipe, updateRecipe } from '../api.js'
  import { emptyForm, formFromRecipe, formProblem, payloadFromForm } from './form.js'

  // recipe: the one being edited, or null to add a new one.
  let { recipe = null, onSaved, onDeleted, onClose } = $props()

  // Filled in once, when the editor opens (it's created afresh each time);
  // after that the fields are the person's to change.
  let form = $state(untrack(() => (recipe ? formFromRecipe(recipe) : emptyForm())))
  let busy = $state(false)
  let error = $state(null)
  let confirmingDelete = $state(false)

  async function save() {
    error = formProblem(form)
    if (error) return
    busy = true
    try {
      const payload = payloadFromForm(form)
      onSaved(recipe ? await updateRecipe(recipe.id, payload) : await createRecipe(payload))
    } catch (err) {
      error = err.message
    } finally {
      busy = false
    }
  }

  async function remove() {
    if (!confirmingDelete) {
      confirmingDelete = true // a second tap, so one stray touch can't lose a recipe
      return
    }
    busy = true
    try {
      await deleteRecipe(recipe.id)
      onDeleted(recipe.id)
    } catch (err) {
      error = err.message
      busy = false
    }
  }
</script>

<!-- Top-aligned: the on-screen keyboard covers the bottom of the screen. -->
<div class="overlay" role="presentation" onclick={onClose}>
  <div class="modal" role="dialog" tabindex="-1" aria-modal="true" aria-label={recipe ? 'Edit recipe' : 'Add a recipe'}
       onclick={(e) => e.stopPropagation()}>
    <h2>{recipe ? 'Edit recipe' : 'Add a recipe'}</h2>

    <label>
      Name
      <input type="text" bind:value={form.title} placeholder="e.g. Grandma's chili" use:vkbd />
    </label>

    <div class="numbers">
      <label>Serves <input type="text" bind:value={form.servings} placeholder="4" use:vkbd /></label>
      <label>Prep (min) <input type="text" bind:value={form.prepMinutes} placeholder="15" use:vkbd /></label>
      <label>Cook (min) <input type="text" bind:value={form.cookMinutes} placeholder="45" use:vkbd /></label>
    </div>

    <label>
      Ingredients <span class="hint">one per line, with amounts: "2 cups flour"</span>
      <textarea rows="7" bind:value={form.ingredients} placeholder={'1 lb ground beef\n1 can kidney beans\n2 tbsp chili powder'}
                use:vkbd></textarea>
    </label>

    <label>
      Steps <span class="hint">one per line</span>
      <textarea rows="6" bind:value={form.steps} placeholder={'Brown the beef.\nAdd everything else and simmer 30 minutes.'}
                use:vkbd></textarea>
    </label>

    <div class="numbers">
      <label>Dietary <span class="hint">comma-separated</span>
        <input type="text" bind:value={form.dietaryTags} placeholder="vegetarian, gluten-free" use:vkbd />
      </label>
      <label>Contains <span class="hint">allergens</span>
        <input type="text" bind:value={form.allergens} placeholder="dairy, nuts" use:vkbd />
      </label>
    </div>

    {#if error}<p class="error">{error}</p>{/if}

    <div class="actions">
      {#if recipe}
        <button type="button" class="danger" disabled={busy} onclick={remove}>
          {confirmingDelete ? 'Tap again to delete' : 'Delete'}
        </button>
      {/if}
      <button type="button" disabled={busy} onclick={onClose}>Cancel</button>
      <button type="button" class="primary" disabled={busy} onclick={save}>{busy ? 'Saving…' : 'Save'}</button>
    </div>
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: 4vh;
    z-index: 1000;
  }

  .modal {
    background: white;
    color: #111;
    border-radius: 0.75rem;
    padding: 1.5rem;
    width: min(92vw, 40rem);
    max-height: 60vh; /* stays clear of the on-screen keyboard */
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  h2 {
    margin: 0 0 0.25rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.9rem;
    flex: 1;
    min-width: 0; /* lets a row of fields share the width instead of overflowing it */
  }

  .hint {
    color: #777;
    font-size: 0.8rem;
  }

  .numbers {
    display: flex;
    gap: 0.75rem;
  }

  input,
  textarea {
    font: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 0.4rem;
    width: 100%;
  }

  textarea {
    resize: vertical;
    line-height: 1.4;
  }

  .error {
    color: #c0392b;
    font-size: 0.9rem;
    margin: 0;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  button {
    font-size: 1rem;
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    border: 1px solid #ccc;
    background: #f2f2f2;
  }

  button.primary {
    background: #2563eb;
    color: white;
    border-color: #2563eb;
  }

  button.danger {
    background: #c0392b;
    color: white;
    border-color: #c0392b;
    margin-right: auto;
  }
</style>
