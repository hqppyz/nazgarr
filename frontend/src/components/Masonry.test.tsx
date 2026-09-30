import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Masonry } from '@/components/Masonry'

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: () => {}, removeEventListener: () => {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  // Altezza di ogni scheda dal suo contenuto (jsdom non fa layout).
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return Number(this.querySelector('[data-h]')?.getAttribute('data-h') ?? 0)
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Masonry', () => {
  it('puts each card in the shortest column, so a tall one does not push the next below it', () => {
    render(
      <Masonry>
        <div data-h="200">match</div>
        <div data-h="900">mediainfo</div>
        <div data-h="300">details</div>
        <div data-h="100">analysis</div>
      </Masonry>,
    )

    const style = (text: string) => screen.getByText(text).parentElement!.style
    expect(style('match').top).toBe('0px')
    expect(style('mediainfo').left).not.toBe('0px')
    expect([style('details').left, style('details').top]).toEqual(['0px', '216px'])
    // Sotto "details", non sotto il MediaInfo alto.
    expect([style('analysis').left, style('analysis').top]).toEqual(['0px', '532px'])
  })
})
