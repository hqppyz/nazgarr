import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RING_STATIC_SRC, RingLogo } from '@/components/RingLogo'

describe('RingLogo', () => {
  it('falls back to the static image when WebGL is not available (jsdom has none)', () => {
    const { container } = render(<RingLogo size={28} />)
    const img = container.querySelector('img')
    expect(img?.getAttribute('src')).toBe(RING_STATIC_SRC)
    expect(container.querySelector('canvas')).toBeNull()
  })
})
