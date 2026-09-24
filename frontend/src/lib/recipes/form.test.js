import { describe, expect, it } from 'vitest'
import { emptyForm, formFromRecipe, formProblem, payloadFromForm } from './form.js'

const filled = (overrides = {}) => ({ ...emptyForm(), title: 'Chili', ingredients: '1 lb beef', ...overrides })

describe('saving', () => {
  it('sends one line per ingredient and step, leaving the tidying to the server', () => {
    const payload = payloadFromForm(filled({ ingredients: '1 lb beef\n- 1 can beans\n', steps: '1. Brown.\n2. Simmer.' }))

    expect(payload.ingredients).toEqual(['1 lb beef', '- 1 can beans', ''])
    expect(payload.steps).toEqual(['1. Brown.', '2. Simmer.'])
  })

  it('turns numbers into numbers and blanks into nothing', () => {
    const payload = payloadFromForm(filled({ servings: ' 6 ', prepMinutes: '15', cookMinutes: '' }))

    expect(payload).toMatchObject({ servings: 6, prep_time_minutes: 15, cook_time_minutes: null })
  })

  it('splits tags on commas', () => {
    const payload = payloadFromForm(filled({ dietaryTags: 'vegetarian, gluten-free,', allergens: ' dairy ' }))

    expect(payload.dietary_tags).toEqual(['vegetarian', 'gluten-free'])
    expect(payload.allergens).toEqual(['dairy'])
  })

  it('trims the name', () => {
    expect(payloadFromForm(filled({ title: '  Chili  ' })).title).toBe('Chili')
  })
})

describe('what stops a save', () => {
  it('a missing name or no ingredients', () => {
    expect(formProblem(filled({ title: '  ' }))).toMatch(/name/)
    expect(formProblem(filled({ ingredients: '\n  \n' }))).toMatch(/ingredient/)
  })

  it('numbers that are not whole numbers', () => {
    expect(formProblem(filled({ servings: 'four' }))).toMatch(/Serves/)
    expect(formProblem(filled({ prepMinutes: '1.5' }))).toMatch(/Prep/)
    expect(formProblem(filled({ cookMinutes: '-3' }))).toMatch(/Cook/)
    expect(formProblem(filled({ servings: '0' }))).toMatch(/at least 1/)
  })

  it('nothing, for a sensible recipe', () => {
    expect(formProblem(filled({ servings: '4', prepMinutes: '10' }))).toBeNull()
  })
})

describe('editing an existing recipe', () => {
  const recipe = {
    title: 'Pancakes',
    servings: 4,
    prep_time_minutes: null,
    cook_time_minutes: 20,
    ingredients: [
      { raw_text: '2 cups flour', name: 'flour', quantity_text: '2 cups' },
      { raw_text: '2 eggs', name: 'eggs', quantity_text: '2' },
    ],
    steps: ['Mix.', 'Cook.'],
    dietary_tags: ['vegetarian'],
    allergens: ['eggs', 'dairy'],
  }

  it('starts from the recipe as written', () => {
    expect(formFromRecipe(recipe)).toEqual({
      title: 'Pancakes',
      servings: '4',
      prepMinutes: '',
      cookMinutes: '20',
      ingredients: '2 cups flour\n2 eggs',
      steps: 'Mix.\nCook.',
      dietaryTags: 'vegetarian',
      allergens: 'eggs, dairy',
    })
  })

  it('saves back unchanged if nothing was edited', () => {
    const payload = payloadFromForm(formFromRecipe(recipe))

    expect(payload).toMatchObject({
      title: 'Pancakes',
      servings: 4,
      prep_time_minutes: null,
      cook_time_minutes: 20,
      ingredients: ['2 cups flour', '2 eggs'],
      steps: ['Mix.', 'Cook.'],
      dietary_tags: ['vegetarian'],
      allergens: ['eggs', 'dairy'],
    })
  })
})
