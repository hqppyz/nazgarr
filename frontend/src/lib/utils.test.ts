import { describe, expect, it } from 'vitest'

import { cn } from '@/lib/utils'

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
