const BASE = '/api'

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    let detail = null
    try {
      detail = (await res.json()).detail
    } catch {
      // response wasn't JSON — fall through to the generic message below
    }
    throw new Error(detail || `API request failed: ${path} (${res.status})`)
  }
  if (res.status === 204) return null
  return res.json()
}

function requestJson(path, method, body) {
  return request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getAccounts() {
  return request('/accounts')
}

export function getEvents(startISO, endISO) {
  const params = new URLSearchParams({ start: startISO, end: endISO })
  return request(`/events?${params}`)
}

export function createEvent(payload) {
  return requestJson('/events', 'POST', payload)
}

export function updateEvent(id, payload) {
  return requestJson(`/events/${id}`, 'PATCH', payload)
}

export function deleteEvent(id) {
  return request(`/events/${id}`, { method: 'DELETE' })
}

export function getWeather() {
  return request('/weather')
}

export function getRecipes() {
  return request('/recipes')
}

export function importRecipe(url) {
  return requestJson('/recipes/import', 'POST', { url })
}

export function getFavoriteRecipeIds(personName) {
  const params = new URLSearchParams({ person_name: personName })
  return request(`/recipes/favorites?${params}`)
}

export function favoriteRecipe(recipeId, personName) {
  const params = new URLSearchParams({ person_name: personName })
  return request(`/recipes/${recipeId}/favorite?${params}`, { method: 'POST' })
}

export function unfavoriteRecipe(recipeId, personName) {
  const params = new URLSearchParams({ person_name: personName })
  return request(`/recipes/${recipeId}/favorite?${params}`, { method: 'DELETE' })
}

export function getAmbientConfig() {
  return request('/ambient/config')
}

export function getAmbientPhotos() {
  return request('/ambient/photos')
}

export function getAmbientStatus() {
  return request('/ambient/status')
}

export function getReminders() {
  return request('/reminders')
}

export function dismissReminder(eventId) {
  return request(`/reminders/${eventId}/dismiss`, { method: 'POST' })
}

export function getMealPlan() {
  return request('/meal-plan')
}

export function setMealPlan(planDate, recipeId) {
  return requestJson(`/meal-plan/${planDate}`, 'PUT', { recipe_id: recipeId })
}
