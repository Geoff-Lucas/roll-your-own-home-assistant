// Between the recipe editor's fields and the API's recipe shape. Ingredients
// and steps are edited as text, one per line; the server does the rest
// (drops blank lines, bullets and step numbers, and parses each ingredient
// into name + quantity, exactly as it does for an imported recipe).

export function emptyForm() {
  return {
    title: '',
    servings: '',
    prepMinutes: '',
    cookMinutes: '',
    ingredients: '',
    steps: '',
    dietaryTags: '',
    allergens: '',
  }
}

const number = (value) => (value == null ? '' : String(value))

export function formFromRecipe(recipe) {
  return {
    title: recipe.title,
    servings: number(recipe.servings),
    prepMinutes: number(recipe.prep_time_minutes),
    cookMinutes: number(recipe.cook_time_minutes),
    ingredients: recipe.ingredients.map((ingredient) => ingredient.raw_text).join('\n'),
    steps: recipe.steps.join('\n'),
    dietaryTags: recipe.dietary_tags.join(', '),
    allergens: recipe.allergens.join(', '),
  }
}

const lines = (text) => text.split('\n')
const list = (text) => text.split(',').map((item) => item.trim()).filter(Boolean)

/** A whole number, or null for blank; NaN for anything else, so it's caught before saving. */
function wholeNumber(text) {
  const trimmed = String(text).trim()
  if (trimmed === '') return null
  return /^\d+$/.test(trimmed) ? Number(trimmed) : NaN
}

/** The problem to show before saving, or null if the form can be saved. */
export function formProblem(form) {
  if (!form.title.trim()) return 'Give the recipe a name.'
  if (!lines(form.ingredients).some((line) => line.trim())) return 'Add at least one ingredient.'
  const numbers = { Serves: form.servings, 'Prep minutes': form.prepMinutes, 'Cook minutes': form.cookMinutes }
  for (const [label, value] of Object.entries(numbers)) {
    if (Number.isNaN(wholeNumber(value))) return `${label} should be a whole number.`
  }
  if (wholeNumber(form.servings) === 0) return 'Serves should be at least 1.'
  return null
}

export function payloadFromForm(form) {
  return {
    title: form.title.trim(),
    servings: wholeNumber(form.servings),
    prep_time_minutes: wholeNumber(form.prepMinutes),
    cook_time_minutes: wholeNumber(form.cookMinutes),
    ingredients: lines(form.ingredients),
    steps: lines(form.steps),
    dietary_tags: list(form.dietaryTags),
    allergens: list(form.allergens),
  }
}
