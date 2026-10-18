import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CrashPanel } from '@/components/CrashPanel'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { lazyPage } from '@/lib/lazyPages'

function Boom({ message }: { message: string }): never {
  throw new Error(message)
}

const boundary = (children: React.ReactNode, resetKey?: unknown) => (
  <ErrorBoundary resetKey={resetKey} fallback={({ error, reset }) => <CrashPanel error={error} onRetry={reset} />}>
    {children}
  </ErrorBoundary>
)

describe('ErrorBoundary', () => {
  // React riporta in console ogni errore preso da un confine: qui è voluto.
  beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => undefined))
  afterEach(() => vi.restoreAllMocks())

  it('shows the error and a reload button instead of a blank page', () => {
    render(boundary(<Boom message="cannot read x of undefined" />))
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('Something went wrong')).toBeTruthy()
    expect(screen.getByText('cannot read x of undefined')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Reload page/ })).toBeTruthy()
  })

  it('tells a missing chunk after an upgrade apart from a bug', () => {
    render(boundary(<Boom message="Failed to fetch dynamically imported module: /assets/HistoryChart-old.js" />))
    expect(screen.getByText('A new version is available')).toBeTruthy()
  })

  it('tries again when the page changes', () => {
    const { rerender } = render(boundary(<Boom message="broken" />, '/a'))
    expect(screen.getByRole('alert')).toBeTruthy()
    rerender(boundary(<p>other page</p>, '/b'))
    expect(screen.getByText('other page')).toBeTruthy()
  })

  it('retries a page whose chunk failed to load once', async () => {
    let attempts = 0
    const Page = lazyPage(
      async () => {
        attempts += 1
        if (attempts === 1) throw new Error('Failed to fetch dynamically imported module')
        return { C: () => <p>loaded</p> }
      },
      (m) => m.C,
      { preload: false },
    )
    render(boundary(<Page />))
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('loaded')).toBeTruthy()
    expect(attempts).toBe(2)
  })
})
