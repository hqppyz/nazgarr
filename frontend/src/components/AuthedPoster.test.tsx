import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthedImage, AuthedPoster } from '@/components/AuthedPoster'

// Un IntersectionObserver finto: `scroll(margine, vicino)` dice a quelli con
// quel rootMargin che i loro elementi sono (o non sono più) entro il margine.
class FakeObserver {
  static all: FakeObserver[] = []
  readonly targets = new Set<Element>()
  readonly callback: IntersectionObserverCallback
  readonly rootMargin: string
  readonly root: Element | Document | null
  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback
    this.rootMargin = options?.rootMargin ?? ''
    this.root = options?.root ?? null
    FakeObserver.all.push(this)
  }
  observe(target: Element) {
    this.targets.add(target)
  }
  unobserve(target: Element) {
    this.targets.delete(target)
  }
  disconnect() {
    this.targets.clear()
    FakeObserver.all = FakeObserver.all.filter((o) => o !== this)
  }
}

function scroll(rootMargin: string, isIntersecting: boolean) {
  act(() => {
    for (const observer of FakeObserver.all.filter((o) => o.rootMargin === rootMargin)) {
      const entries = [...observer.targets].map((target) => ({ target, isIntersecting }) as IntersectionObserverEntry)
      observer.callback(entries, observer as unknown as IntersectionObserver)
    }
  })
}

describe('AuthedPoster', () => {
  const original = globalThis.IntersectionObserver
  beforeEach(() => {
    FakeObserver.all = []
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
    let n = 0
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:poster-${++n}`)
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  })
  afterEach(() => {
    globalThis.IntersectionObserver = original
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const posterFetch = () =>
    // Corpo testo: il Blob di jsdom non è quello che la Response di Node legge.
    vi.fn(async () => new Response('jpg', { status: 200, headers: { 'Content-Type': 'image/jpeg' } }))

  it('aborts the poster download when the card goes away before it arrives', () => {
    const signals: AbortSignal[] = []
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      signals.push(init.signal as AbortSignal)
      return new Promise<Response>(() => {})
    }))
    const { unmount } = render(<AuthedPoster contentType="movie" tmdbId={603} hasPoster release />)
    scroll('300px', true)
    expect(signals).toHaveLength(1)
    expect(signals[0].aborted).toBe(false)
    unmount()
    expect(signals[0].aborted).toBe(true)
  })

  it('downloads only near the screen, and frees the blob once the card is far from it', async () => {
    const fetch = posterFetch()
    vi.stubGlobal('fetch', fetch)
    const { container } = render(<AuthedPoster contentType="movie" tmdbId={603} hasPoster release />)
    expect(fetch).not.toHaveBeenCalled()

    scroll('300px', true)
    await waitFor(() => expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:poster-1'))
    expect(container.querySelector('img')?.getAttribute('decoding')).toBe('async')

    // Scorsa lontano: il blob si libera, al suo posto il segnaposto.
    scroll('300px', false)
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    scroll('1500px', false)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:poster-1')
    expect(container.querySelector('img')).toBeNull()

    // Di nuovo vicina: si richiede (al browser, che lo ha in cache).
    scroll('1500px', true)
    scroll('300px', true)
    await waitFor(() => expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:poster-2'))
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('watches every poster of a grid with one observer per margin', () => {
    vi.stubGlobal('fetch', posterFetch())
    const { unmount } = render(
      <>
        {[1, 2, 3, 4].map((id) => (
          <AuthedPoster key={id} contentType="movie" tmdbId={id} hasPoster release />
        ))}
      </>,
    )
    expect(FakeObserver.all.map((o) => [o.rootMargin, o.targets.size])).toEqual([['300px', 4], ['1500px', 4]])
    unmount()
    expect(FakeObserver.all).toEqual([])
  })

  it("measures the distance against the page's scrolling area, not the window", () => {
    vi.stubGlobal('fetch', posterFetch())
    // La finestra non scorre: con la radice implicita l'area che scorre
    // taglierebbe senza margine. Il contenitore overflow-x-auto di una
    // tabella in mezzo non conta: non scorre in verticale.
    const { container } = render(
      <>
        <div data-scroll-root>
          <div className="overflow-x-auto">
            <AuthedPoster contentType="movie" tmdbId={1} hasPoster release />
            <AuthedPoster contentType="movie" tmdbId={2} hasPoster release />
          </div>
        </div>
        <AuthedPoster contentType="movie" tmdbId={3} hasPoster release />
      </>,
    )
    const area = container.querySelector('[data-scroll-root]')
    expect(FakeObserver.all.map((o) => [o.root, o.rootMargin, o.targets.size])).toEqual([
      [area, '300px', 2],
      [area, '1500px', 2],
      [null, '300px', 1],
      [null, '1500px', 1],
    ])
  })

  it('keeps the poster of a detail view once loaded, without watching it any more', async () => {
    vi.stubGlobal('fetch', posterFetch())
    const { container } = render(<AuthedPoster contentType="movie" tmdbId={603} hasPoster />)
    expect(FakeObserver.all.map((o) => o.rootMargin)).toEqual(['300px'])
    scroll('300px', true)
    await waitFor(() => expect(container.querySelector('img')).not.toBeNull())
    expect(FakeObserver.all).toEqual([])
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })

  it('asks nothing for a title without a poster', () => {
    const fetch = posterFetch()
    vi.stubGlobal('fetch', fetch)
    render(<AuthedPoster contentType="movie" tmdbId={603} hasPoster={false} release />)
    scroll('300px', true)
    expect(fetch).not.toHaveBeenCalled()
    expect(FakeObserver.all).toEqual([])
  })

  it('keeps a small image once loaded, without watching it any more', async () => {
    vi.stubGlobal('fetch', posterFetch())
    const { container } = render(<AuthedImage url="/api/trackers/1/icon" fallback={null} />)
    scroll('300px', true)
    await waitFor(() => expect(container.querySelector('img')).not.toBeNull())
    expect(FakeObserver.all).toEqual([])
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  })
})
