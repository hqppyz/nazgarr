import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthedPoster } from '@/components/AuthedPoster'

describe('AuthedPoster', () => {
  const original = globalThis.IntersectionObserver
  let reveal: () => void = () => {}
  beforeEach(() => {
    class FakeObserver {
      constructor(cb: IntersectionObserverCallback) {
        reveal = () => cb([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
      }
      observe() {}
      disconnect() {}
    }
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
  })
  afterEach(() => {
    globalThis.IntersectionObserver = original
    vi.unstubAllGlobals()
  })

  it('aborts the poster download when the card goes away before it arrives', () => {
    const signals: AbortSignal[] = []
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      signals.push(init.signal as AbortSignal)
      return new Promise<Response>(() => {})
    }))
    const { unmount } = render(<AuthedPoster contentType="movie" tmdbId={603} hasPoster />)
    act(() => reveal())
    expect(signals).toHaveLength(1)
    expect(signals[0].aborted).toBe(false)
    unmount()
    expect(signals[0].aborted).toBe(true)
  })
})
