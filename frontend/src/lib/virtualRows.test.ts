import { describe, expect, it } from 'vitest'

import {
  anchorAt,
  anchorShift,
  gapKey,
  mergeHeights,
  nextRange,
  nextRowWith,
  rowAt,
  rowOffsets,
  rowsBetween,
  windowSlots,
  type RowSlot,
} from '@/lib/virtualRows'

const keysOf = (n: number) => Array.from({ length: n }, (_, i) => `r${i}`)
const even = (n: number, height = 20) => rowOffsets(keysOf(n), new Map(), height)

describe('row offsets', () => {
  it('adds up the measured heights and the estimate for the rows never measured', () => {
    const offsets = rowOffsets(['a', 'b', 'c'], new Map([['b', 50]]), 20)
    expect([...offsets]).toEqual([0, 20, 70, 90])
  })

  it('finds the row under a point, clamped to the list', () => {
    const offsets = rowOffsets(['a', 'b', 'c'], new Map([['b', 50]]), 20)
    expect(rowAt(offsets, -100)).toBe(0)
    expect(rowAt(offsets, 0)).toBe(0)
    expect(rowAt(offsets, 19.9)).toBe(0)
    expect(rowAt(offsets, 20)).toBe(1)
    expect(rowAt(offsets, 69)).toBe(1)
    expect(rowAt(offsets, 70)).toBe(2)
    expect(rowAt(offsets, 10_000)).toBe(2)
    expect(rowAt(rowOffsets([], new Map(), 20), 5)).toBe(0)
  })

  it('takes the rows touching a span, at least one', () => {
    const offsets = even(100)
    expect(rowsBetween(offsets, 100, 199)).toEqual({ start: 5, end: 10 })
    expect(rowsBetween(offsets, -500, -100)).toEqual({ start: 0, end: 1 }) // la lista è più in basso
    expect(rowsBetween(offsets, 5000, 6000)).toEqual({ start: 99, end: 100 }) // la lista è finita sopra
    expect(rowsBetween(even(0), 0, 100)).toEqual({ start: 0, end: 0 })
  })
})

describe('nextRange', () => {
  const offsets = even(1000)

  it('keeps the mounted window while it covers the view plus the near margin', () => {
    const current = { start: 100, end: 200 }
    // Vista 2400-2800 (righe 120-140), ±200 px: righe 110-150, dentro la finestra.
    expect(nextRange(current, offsets, { top: 2400, bottom: 2800 }, 200, 600)).toBe(current)
  })

  it('moves it, with the far margin, once the view gets near its edge', () => {
    const current = { start: 100, end: 200 }
    // Vista 3600-4000 (righe 180-200), ±200 px: oltre la riga 200.
    expect(nextRange(current, offsets, { top: 3600, bottom: 4000 }, 200, 600)).toEqual({ start: 150, end: 231 })
  })

  it('starts from scratch without a window or with a list that got shorter', () => {
    expect(nextRange(null, offsets, { top: 0, bottom: 400 }, 200, 600)).toEqual({ start: 0, end: 51 })
    expect(nextRange({ start: 0, end: 2000 }, offsets, { top: 0, bottom: 400 }, 200, 600)).toEqual({ start: 0, end: 51 })
    expect(nextRange({ start: 0, end: 10 }, even(0), { top: 0, bottom: 400 }, 200, 600)).toEqual({ start: 0, end: 0 })
  })
})

describe('windowSlots', () => {
  const height = (slots: RowSlot[]) =>
    slots.reduce((sum, slot) => sum + (slot.kind === 'gap' ? slot.height : 20), 0)
  const rows = (slots: RowSlot[]) => slots.flatMap((slot) => (slot.kind === 'row' ? [slot.index] : []))

  it('renders the window with the space of the rows above and below', () => {
    const slots = windowSlots({ start: 10, end: 13 }, [], even(20))
    expect(slots).toEqual([
      { kind: 'gap', key: gapKey(0), height: 200 },
      { kind: 'row', index: 10 },
      { kind: 'row', index: 11 },
      { kind: 'row', index: 12 },
      { kind: 'gap', key: gapKey(13), height: 140 },
    ])
  })

  it('keeps the focused or open rows outside the window in their place', () => {
    const slots = windowSlots({ start: 10, end: 13 }, [2, 18, 11, 2, -1, 99], even(20))
    expect(rows(slots)).toEqual([2, 10, 11, 12, 18])
    // Ogni riga resta dove sarebbe nell'albero intero: l'altezza totale non cambia.
    expect(height(slots)).toBe(400)
    expect(slots[0]).toEqual({ kind: 'gap', key: gapKey(0), height: 40 })
    expect(slots[2]).toEqual({ kind: 'gap', key: gapKey(3), height: 140 })
  })

  it('needs no space when the window reaches the ends', () => {
    expect(windowSlots({ start: 0, end: 3 }, [], even(3)).every((slot) => slot.kind === 'row')).toBe(true)
    expect(windowSlots({ start: 5, end: 50 }, [], even(3))).toEqual([{ kind: 'gap', key: gapKey(0), height: 60 }])
  })
})

describe('anchor', () => {
  it('has none while the start of the list is in view', () => {
    expect(anchorAt(even(100), keysOf(100), 0)).toBeNull()
    expect(anchorAt(even(100), keysOf(100), -300)).toBeNull()
  })

  it('keeps the row at the top of the view when rows above it go away', () => {
    const anchor = anchorAt(even(100), keysOf(100), 1005)
    expect(anchor).toEqual({ key: 'r50', offset: -5 })
    // Un'esclusione toglie 10 righe sopra: la vista sale di 200 px.
    const keys = keysOf(100).slice(10)
    const shift = anchorShift(anchor!, rowOffsets(keys, new Map(), 20), new Map(keys.map((k, i) => [k, i])), 1005)
    expect(shift).toBe(-200)
  })

  it('keeps it when rows above it are measured taller than the estimate', () => {
    const keys = keysOf(100)
    const anchor = anchorAt(even(100), keys, 1000)!
    const measured = rowOffsets(keys, new Map([['r10', 60], ['r11', 60]]), 20)
    expect(anchorShift(anchor, measured, new Map(keys.map((k, i) => [k, i])), 1000)).toBe(80)
  })

  it('leaves the view alone when its row is gone', () => {
    expect(anchorShift({ key: 'gone', offset: 0 }, even(10), new Map(), 100)).toBe(0)
  })
})

describe('nextRowWith', () => {
  it('skips the rows with nothing to focus, mounted or not, and stops at the ends', () => {
    const has = (i: number) => i % 3 === 0
    expect(nextRowWith(0, 1, 10, has)).toBe(3)
    expect(nextRowWith(3, -1, 10, has)).toBe(0)
    expect(nextRowWith(9, 1, 10, has)).toBeNull()
    expect(nextRowWith(0, -1, 10, has)).toBeNull()
  })
})

describe('mergeHeights', () => {
  const start = { heights: new Map([['a', 20]]), estimate: 20 }

  it('keeps the same object when nothing changed, so nothing redraws', () => {
    expect(mergeHeights(start, [['a', 20.2], ['b', 0]])).toBe(start)
  })

  it('makes the average of the first rows measured the estimate', () => {
    const first = mergeHeights({ heights: new Map(), estimate: 33 }, [['a', 20], ['b', 40], ['c', 0]])
    expect([...first.heights]).toEqual([['a', 20], ['b', 40]])
    expect(first.estimate).toBe(30)
  })

  it('records new heights and keeps the estimate until the measures are cleared', () => {
    const next = mergeHeights(start, [['a', 20], ['b', 40], ['c', 60]])
    expect([...next.heights]).toEqual([['a', 20], ['b', 40], ['c', 60]])
    // Le righe mai montate restano dov'erano: si spostano solo quelle misurate.
    expect(next.estimate).toBe(20)
    expect(start.heights.size).toBe(1) // mai modificato sul posto
    // Dopo un cambio di larghezza (misure vuote) la stima riparte dalle prime righe misurate.
    expect(mergeHeights({ heights: new Map(), estimate: next.estimate }, [['d', 50]]).estimate).toBe(50)
  })

  it("never gives a gap a key a file's path can have", () => {
    const slots = windowSlots({ start: 1, end: 2 }, [], even(3))
    expect(slots.filter((slot) => slot.kind === 'gap').map((slot) => slot.key)).toEqual(['\0gap-0', '\0gap-2'])
  })
})
