import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { UploadQueuePage } from '@/pages/upload/UploadQueuePage'

const reorder = vi.fn()
const job = (id: number, status: string, extra = {}) => ({
  id, status, title: `Movie ${id}`, year: 2024, kind: 'movie', relative_path: `m${id}.mkv`, tmdb_id: null,
  content_type: null, poster_path: null, queue_position: null, progress_done: null, progress_total: null,
  finished_at: null, targets: [], ...extra,
})

vi.mock('@/api/hooks/uploads', () => ({
  useUploads: () => ({
    isPending: false,
    data: [
      job(4, 'done', { finished_at: '2026-09-30T10:00:00', targets: [
        { id: 1, tracker_label: 'ITT', action: 'upload', status: 'done' },
        { id: 2, tracker_label: 'Other', action: 'upload', status: 'failed' },
      ] }),
      job(3, 'queued', { queue_position: 2 }),
      job(2, 'queued', { queue_position: 1 }),
      job(1, 'running', { progress_done: 5, progress_total: 10 }),
    ],
  }),
  useReorderQueue: () => ({ mutate: reorder, isPending: false }),
  useUpload: () => ({ data: undefined }),
}))
vi.mock('@/components/AuthedPoster', () => ({ AuthedPoster: () => null }))

afterEach(cleanup)

describe('UploadQueuePage', () => {
  it('lists what is running first, then the queue in order, and reorders it', () => {
    render(<MemoryRouter><UploadQueuePage /></MemoryRouter>)

    const titles = screen.getAllByText(/^Movie \d \(2024\)$/).map((el) => el.textContent)
    expect(titles).toEqual(['Movie 1 (2024)', 'Movie 2 (2024)', 'Movie 3 (2024)'])
    fireEvent.click(screen.getAllByTitle('Later in the queue')[0])
    expect(reorder).toHaveBeenCalledWith([3, 2], expect.anything())
  })
})
