import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { lazyPage, preloadPages } from '@/lib/lazyPages'

afterEach(() => vi.useRealTimers())

describe('preloadPages', () => {
  it('waits for the open page, then loads the pages one at a time', async () => {
    vi.useFakeTimers()
    const order: string[] = []
    const deferred: Record<string, () => void> = {}
    const make = (name: string) =>
      lazyPage(
        () => new Promise<{ C: () => null }>((resolve) => {
          order.push(name)
          deferred[name] = () => resolve({ C: () => null })
        }),
        (m) => m.C,
      )
    make('a')
    make('b')
    let busy = true
    const stop = preloadPages(() => busy)

    await vi.advanceTimersByTimeAsync(3000)
    expect(order).not.toContain('a') // la pagina aperta sta ancora caricando

    busy = false
    await vi.advanceTimersByTimeAsync(1000)
    expect(order.filter((n) => n === 'a' || n === 'b')).toEqual(['a']) // una alla volta
    deferred.a()
    await vi.advanceTimersByTimeAsync(1000)
    expect(order).toContain('b')
    stop()
  })
})

describe('lazyPage', () => {
  it('renders an already loaded page right away, without the loading ring', async () => {
    let loads = 0
    const Page = lazyPage(
      async () => {
        loads += 1
        return { C: () => <p>ready</p> }
      },
      (m) => m.C,
      { preload: false },
    )
    const first = render(<Page />)
    expect(screen.getByRole('status')).toBeInTheDocument() // l'anello mentre scarica
    expect(await screen.findByText('ready')).toBeInTheDocument()
    first.unmount()

    await act(async () => {
      render(<Page />)
    })
    expect(screen.getByText('ready')).toBeInTheDocument()
    expect(screen.queryByRole('status')).toBeNull()
    expect(loads).toBe(1)
  })
})
