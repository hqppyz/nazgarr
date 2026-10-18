import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { HISTORY_KEY, useHistoryFollowsQueue } from '@/api/hooks/uploads'

describe('useHistoryFollowsQueue', () => {
  it('reloads the history only when a job leaves the queue, not on every poll', () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { rerender } = renderHook(({ ids }) => useHistoryFollowsQueue(ids), {
      initialProps: { ids: [1, 2] },
      wrapper,
    })

    rerender({ ids: [1, 2] })
    rerender({ ids: [1, 2, 3] }) // un job nuovo in coda
    expect(invalidate).not.toHaveBeenCalled()

    rerender({ ids: [2, 3] }) // il primo è finito
    expect(invalidate).toHaveBeenCalledWith({ queryKey: HISTORY_KEY })
  })
})
