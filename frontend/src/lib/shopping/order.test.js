import { describe, expect, it } from 'vitest'
import { leftToBuy, ordered, summary } from './order.js'

const item = (name, checked = false) => ({ key: name, name, quantity: '', recipes: [], checked, manual: false })

describe('ordering', () => {
  it('puts what is left to buy first and ticked items last, each keeping its order', () => {
    const items = [item('apples', true), item('bread'), item('carrots', true), item('dates')]

    expect(ordered(items).map((i) => i.name)).toEqual(['bread', 'dates', 'apples', 'carrots'])
  })

  it('does not change the list it was given', () => {
    const items = [item('apples', true), item('bread')]

    ordered(items)

    expect(items.map((i) => i.name)).toEqual(['apples', 'bread'])
  })

  it('counts what is left', () => {
    expect(leftToBuy([item('a', true), item('b'), item('c')])).toBe(2)
  })
})

describe('the summary line', () => {
  it('says how many meals it covers and how much is left', () => {
    expect(summary({ meals: 3, items: [item('a'), item('b', true)] })).toBe('3 meals · 1 to buy')
    expect(summary({ meals: 1, items: [item('a')] })).toBe('1 meal · 1 to buy')
  })

  it('says when everything is ticked off', () => {
    expect(summary({ meals: 2, items: [item('a', true)] })).toBe('2 meals · all done')
  })

  it('explains an empty list rather than showing nothing', () => {
    expect(summary({ meals: 0, items: [] })).toBe('No meals planned for the rest of the week yet')
    expect(summary({ meals: 2, items: [] })).toBe('2 meals planned, nothing to buy')
  })

  it('still shows hand-added items when there are no meals', () => {
    expect(summary({ meals: 0, items: [item('paper towels')] })).toBe('1 to buy')
  })
})
