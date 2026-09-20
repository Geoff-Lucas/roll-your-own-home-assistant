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

export function getLocations() {
  return request('/locations')
}

export function searchLocations(query) {
  return request(`/locations/search?${new URLSearchParams({ q: query })}`)
}

export function addLocation(candidate) {
  return requestJson('/locations', 'POST', candidate)
}

export function selectLocation(id) {
  return request(`/locations/${id}/select`, { method: 'POST' })
}

export function deleteLocation(id) {
  return request(`/locations/${id}`, { method: 'DELETE' })
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

export function getBrowserState() {
  return request('/browser/state')
}

export function showBrowser(rect) {
  return requestJson('/browser/show', 'POST', rect)
}

export function hideBrowser() {
  return request('/browser/hide', { method: 'POST' })
}

export function navigateBrowser(address) {
  return requestJson('/browser/navigate', 'POST', { address })
}

export function browserBack() {
  return request('/browser/back', { method: 'POST' })
}

export function browserForward() {
  return request('/browser/forward', { method: 'POST' })
}

export function browserReload() {
  return request('/browser/reload', { method: 'POST' })
}

export function importCurrentPage() {
  return request('/browser/import-current', { method: 'POST' })
}

export function getTimers() {
  return request('/timers')
}

export function createTimer(payload) {
  return requestJson('/timers', 'POST', payload)
}

// action: pause | resume | reset | dismiss  (snooze takes { minutes })
export function timerAction(id, action, body) {
  return body
    ? requestJson(`/timers/${id}/${action}`, 'POST', body)
    : request(`/timers/${id}/${action}`, { method: 'POST' })
}

export function deleteTimer(id) {
  return request(`/timers/${id}`, { method: 'DELETE' })
}

export function testChime() {
  return request('/timers/test-chime', { method: 'POST' })
}

export function getVoiceStatus() {
  return request('/voice/status')
}

export function getVoiceState() {
  return request('/voice/state')
}

export function startVoice() {
  return request('/voice/start', { method: 'POST' })
}

export function stopVoice() {
  return request('/voice/stop', { method: 'POST' })
}

export function sendVoiceText(text, speak = true) {
  return requestJson('/voice/text', 'POST', { text, speak })
}
