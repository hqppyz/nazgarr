import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { ResultStep } from '@/components/upload/ResultStep'

afterEach(cleanup)

describe('ResultStep', () => {
  it('shows each tracker outcome, the tracker link and why one failed', () => {
    const job = {
      status: 'partial',
      targets: [
        { id: 1, tracker_label: 'ITT', action: 'upload', status: 'done', approved_name: 'Movie (2024)',
          remote_url: 'https://itt/torrents/5', error_message: 'seed_failed' },
        { id: 2, tracker_label: 'Other', action: 'upload', status: 'failed', approved_name: 'Movie (2024)',
          remote_url: null, error_message: 'rejected' },
      ],
      events: [
        { id: 1, target_id: 2, level: 'error', code: 'upload_failed', params: { error: 'rejected: dupe' }, created_at: '' },
      ],
    } as unknown as UploadJob

    render(
      <QueryClientProvider client={new QueryClient()}>
        <ResultStep job={job} />
      </QueryClientProvider>,
    )

    expect(screen.getByText('Partly done: some trackers failed')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open on the tracker/ }).getAttribute('href')).toBe('https://itt/torrents/5')
    expect(screen.getByText(/adding it to the client failed/)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Retry seeding/ })).toHaveLength(1) // solo dove il seed è fallito
    expect(screen.getByText('Upload failed: rejected: dupe')).toBeTruthy()
  })
})
