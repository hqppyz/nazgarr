import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useRingLoader } from '@/components/RingLoader'

type Query = Parameters<typeof useRingLoader>[0]

const base: Query = { data: undefined, isPending: true, isError: false, isFetching: true, error: null, refetch: vi.fn() }

function Page({ query }: { query: Query }) {
  const loader = useRingLoader(query)
  return loader ?? <p>page</p>
}

describe('useRingLoader', () => {
  afterEach(cleanup)

  it('shows the ring while loading, then the page after the ring has gone', async () => {
    vi.useFakeTimers()
    const { rerender } = render(<Page query={base} />)
    expect(screen.getByRole('status')).toBeTruthy()
    rerender(<Page query={{ ...base, data: [], isPending: false, isFetching: false }} />)
    expect(screen.queryByText('page')).toBeNull() // il tempo della O
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(screen.getByText('page')).toBeTruthy()
    vi.useRealTimers()
  })

  it('shows the page straight away when the data is already there', () => {
    render(<Page query={{ ...base, data: [], isPending: false, isFetching: false }} />)
    expect(screen.getByText('page')).toBeTruthy()
  })

  it('stays on the fallen ring with the error and a retry', () => {
    const refetch = vi.fn()
    const failed = { ...base, isPending: false, isFetching: false, isError: true, error: new Error('boom'), refetch }
    render(<Page query={failed} />)
    expect(screen.getByText('boom')).toBeTruthy()
    fireEvent.click(screen.getByRole('button'))
    expect(refetch).toHaveBeenCalled()
  })
})
