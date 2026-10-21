import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { HISTORY_KEY, uploadPollInterval, useHistoryFollowsQueue, type UploadJobSummary } from '@/api/hooks/uploads'

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

describe('uploadPollInterval', () => {
  const job = (status: string, targets: { status: string; error_message: string | null }[]) =>
    ({ status, targets }) as unknown as UploadJobSummary

  it('keeps polling, slower, while a torrent waits for its recheck', () => {
    // Audit 2026-10-18 (R11): finito il job, la pagina smetteva di
    // aggiornarsi, e l'avviso "fermo fino al recheck" restava anche dopo l'avvio.
    expect(uploadPollInterval(job('running', [{ status: 'uploading', error_message: null }]))).toBe(2000)
    expect(uploadPollInterval(job('done', [{ status: 'done', error_message: 'seed_recheck_pending' }]))).toBe(10_000)
    expect(uploadPollInterval(job('partial', [{ status: 'done', error_message: 'seed_recheck_failed' }]))).toBe(false)
    expect(uploadPollInterval(job('done', [{ status: 'done', error_message: null }]))).toBe(false)
    expect(uploadPollInterval(undefined)).toBe(false)
  })
})
