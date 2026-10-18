import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useTrackerDeletePreview } from '@/api/hooks/trackers'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useTrackerDeletePreview', () => {
  it('forgets the counts when the confirmation closes, so reopening never shows the old ones', async () => {
    let candidates = 3
    const pending: { answer?: () => void } = {}
    const reply = () => ({ data: { candidates, busy: false }, response: new Response() })
    vi.spyOn(api, 'GET').mockImplementation((() => {
      if (candidates === 3) return Promise.resolve(reply())
      // La seconda lettura resta in sospeso finché il test non la sblocca.
      return new Promise((resolve) => {
        pending.answer = () => resolve(reply())
      })
    }) as never)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result, rerender } = renderHook(({ open }) => useTrackerDeletePreview(7, open), {
      initialProps: { open: true },
      wrapper,
    })
    await waitFor(() => expect(result.current.data?.candidates).toBe(3))

    rerender({ open: false })
    candidates = 9
    rerender({ open: true })
    // Mentre arriva il conteggio nuovo, quello vecchio non c'è più.
    expect(result.current.data).toBeUndefined()
    expect(result.current.isFetching).toBe(true)

    pending.answer?.()
    await waitFor(() => expect(result.current.data?.candidates).toBe(9))
  })
})
