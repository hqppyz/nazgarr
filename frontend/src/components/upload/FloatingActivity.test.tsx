import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { FloatingActivity } from '@/components/upload/FloatingActivity'

afterEach(cleanup)

const job = {
  targets: [],
  events: [
    { id: 1, target_id: null, level: 'info', code: 'identify_started', params: {}, created_at: '2026-09-30T10:00:00' },
    { id: 2, target_id: null, level: 'info', code: 'analysis_done', params: {}, created_at: '2026-09-30T10:01:00' },
  ],
} as unknown as UploadJob

describe('FloatingActivity', () => {
  it('shows only the last step until opened', () => {
    render(<FloatingActivity job={job} />)

    expect(screen.getByText('Analysis done: waiting for your decision.')).toBeTruthy()
    expect(screen.queryByText('Identification started.')).toBeNull()

    fireEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByText('Identification started.')).toBeTruthy()
  })
})
