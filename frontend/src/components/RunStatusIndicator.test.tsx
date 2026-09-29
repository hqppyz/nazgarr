import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RunStatusIndicator } from '@/components/RunStatusIndicator'

const finished = {
  id: 7, run_type: 'manual', started_at: '2026-09-28T10:00:00Z', finished_at: '2026-09-28T10:05:00Z',
  current_phase: null, phase_total: null, phase_done: null, phase_detail: null, phases: {}, items_scanned: 10,
  matches_found: 0, auto_executed: 0, pending_review: 0, errors: 0, last_error: null, error_messages: [],
  cancel_requested: false, cancelled: false,
}

vi.mock('@/api/hooks/runs', () => ({
  useRuns: () => ({ data: [finished] }),
  useStopRun: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('RunStatusIndicator', () => {
  beforeEach(() => localStorage.clear())

  it('keeps the summary of a finished scan until it is closed, also after a reload', () => {
    const { unmount } = render(<RunStatusIndicator />)
    expect(screen.getByText('Scan completed')).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Dismiss'))
    expect(screen.queryByText('Scan completed')).toBeNull()

    unmount()
    render(<RunStatusIndicator />) // ricarica: resta chiuso
    expect(screen.queryByText('Scan completed')).toBeNull()
  })
})
