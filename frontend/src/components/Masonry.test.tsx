import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Masonry } from '@/components/Masonry'

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: () => {}, removeEventListener: () => {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  // Altezza di ogni scheda dal suo data-h (jsdom non fa layout).
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return Number(this.getAttribute('data-h') ?? 0)
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const style = (text: string) => screen.getByText(text).style

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

    expect(style('match').top).toBe('0px')
    expect(style('mediainfo').left).not.toBe('0px')
    expect([style('details').left, style('details').top]).toEqual(['0px', '216px'])
    expect([style('analysis').left, style('analysis').top]).toEqual(['0px', '532px'])
  })

  it('lays out the cards of a fragment and puts a full-width card below both columns', () => {
    function Section() {
      return (
        <>
          <div data-h="100">a</div>
          <div data-h="300">b</div>
          <div data-h="50" data-masonry="full">wide</div>
          <div data-h="10">after</div>
        </>
      )
    }
    render(
      <Masonry>
        <Section />
      </Masonry>,
    )

    expect([style('wide').top, style('wide').width]).toEqual(['316px', '100%'])
    expect([style('after').top, style('after').left]).toEqual(['382px', '0px'])
  })
})

describe('Masonry heights', () => {
  it('never lets a card stretch to the height of the layout', () => {
    render(
      <Masonry>
        <div data-h="100" className="h-full">short</div>
        <div data-h="500">tall</div>
      </Masonry>,
    )
    expect(screen.getByText('short').style.height).toBe('auto')
  })
})
