import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PosterView } from '@/pages/library/PosterView'

let items: unknown[] = []
vi.mock('@/api/hooks/library', () => ({
  useLibraryItems: () => ({ data: items, isPending: false, isError: false, isFetching: false, error: null, refetch: vi.fn() }),
}))
vi.mock('@/pages/library/ItemDetailSheet', () => ({ ItemDetailSheet: () => null }))
vi.mock('@/components/AuthedPoster', () => ({ AuthedPoster: () => null }))

const movie = (id: number, state = 'seeding') => ({
  content_type: 'movie', tmdb_id: id, title: `Movie ${String(id).padStart(3, '0')}`, year: 2000, has_poster: false,
  files: [{ state, excluded: false, size_bytes: 1, in_review: false, duplicate: false }],
})

describe('PosterView incremental grid', () => {
  const callbacks: IntersectionObserverCallback[] = []
  const original = globalThis.IntersectionObserver
  beforeEach(() => {
    class FakeObserver {
      constructor(cb: IntersectionObserverCallback) {
        callbacks.push(cb)
      }
      observe() {}
      disconnect() {}
    }
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
  })
  afterEach(() => {
    globalThis.IntersectionObserver = original
  })

  it('keeps the posters already shown when the data refreshes, starts over on a new search', () => {
    items = Array.from({ length: 100 }, (_, i) => movie(i))
    const view = () => <MemoryRouter><PosterView /></MemoryRouter>
    const { rerender } = render(view())
    const cards = () => screen.queryAllByRole('button', { name: /Movie \d+ \(2000\)/ }).length
    expect(cards()).toBe(40)
    act(() => callbacks.at(-1)!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
    expect(cards()).toBe(80)

    items = Array.from({ length: 100 }, (_, i) => movie(i, i % 2 ? 'seeding' : 'orphan_media'))
    rerender(view())
    expect(cards()).toBe(80)

    fireEvent.change(screen.getByPlaceholderText(/Search/), { target: { value: 'Movie' } })
    expect(cards()).toBe(40)
  })
})
