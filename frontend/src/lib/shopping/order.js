/** What's left to buy comes first, in the order the server sent; ticked items sink to the bottom. */
export function ordered(items) {
  return [...items.filter((item) => !item.checked), ...items.filter((item) => item.checked)]
}

export function leftToBuy(items) {
  return items.filter((item) => !item.checked).length
}

/** The line under the title: what the list was built from, and how much of it is left. */
export function summary(list) {
  const left = leftToBuy(list.items)
  const meals = list.meals === 1 ? '1 meal' : `${list.meals} meals`
  if (list.items.length === 0) {
    return list.meals === 0 ? 'No meals planned for the rest of the week yet' : `${meals} planned, nothing to buy`
  }
  const buy = left === 0 ? 'all done' : `${left} to buy`
  return list.meals === 0 ? buy : `${meals} · ${buy}`
}
