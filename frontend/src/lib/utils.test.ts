import { describe, expect, it } from 'vitest'

import { cn, selectLabel } from '@/lib/utils'

interface Item {
  id: string
  label: string
}

const items: Item[] = [
  { id: '1', label: 'movie' },
  { id: '2', label: 'tv' },
]

describe('selectLabel', () => {
  it('returns the placeholder when no value is selected', () => {
    // Il gotcha di Base UI: Select.Value con `children` perde il fallback
    // al `placeholder` automatico, va gestito qui esplicitamente.
    expect(selectLabel(items, null, (i) => i.id, (i) => i.label, 'Scegli…')).toBe('Scegli…')
    expect(selectLabel(items, '', (i) => i.id, (i) => i.label, 'Scegli…')).toBe('Scegli…')
  })

  it('returns the matching item label', () => {
    expect(selectLabel(items, '2', (i) => i.id, (i) => i.label, 'Scegli…')).toBe('tv')
  })

  it('falls back to the raw value when nothing matches', () => {
    expect(selectLabel(items, '99', (i) => i.id, (i) => i.label, 'Scegli…')).toBe('99')
  })

  it('falls back to the raw value when items are not loaded yet', () => {
    expect(selectLabel<Item>(undefined, '2', (i) => i.id, (i) => i.label, 'Scegli…')).toBe('2')
  })
})

describe('cn', () => {
  it('lets a side-prefixed width override the sheet default (a plain sm:max-w-* would not)', () => {
    const base = 'data-[side=right]:w-3/4 data-[side=right]:sm:max-w-sm'
    expect(cn(base, 'data-[side=right]:w-full data-[side=right]:sm:max-w-5xl')).toBe(
      'data-[side=right]:w-full data-[side=right]:sm:max-w-5xl',
    )
    // La forma sbagliata tiene entrambe le classi: vince quella del Sheet.
    expect(cn(base, 'sm:max-w-5xl')).toContain('data-[side=right]:sm:max-w-sm')
  })
})
