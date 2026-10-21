import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { UploadQueuePage } from '@/pages/upload/UploadQueuePage'

const reorder = vi.fn()
const remove = vi.fn(() => Promise.resolve())
const cancel = vi.fn(() => Promise.resolve())
const job = (id: number, status: string, extra = {}) => ({
  id, status, title: `Movie ${id}`, year: 2024, kind: 'movie', relative_path: `m${id}.mkv`, tmdb_id: null,
  content_type: null, poster_path: null, queue_position: null, progress_done: null, progress_total: null,
  finished_at: null, targets: [], ...extra,
})

const fetchNextPage = vi.fn()
const history = { hasNextPage: true, isFetchingNextPage: false }
// Uno storico che non arriva (un'istanza remota di prima, un 5xx): null = arriva.
const refetchHistory = vi.fn()
let historyError: Error | null = null

vi.mock('@/api/hooks/uploads', () => ({
  // La coda: solo i job non finiti (GET /api/uploads?scope=active).
  useUploads: () => ({
    isPending: false,
    data: [
      job(3, 'queued', { queue_position: 2 }),
      job(2, 'queued', { queue_position: 1 }),
      job(1, 'running', { progress_done: 5, progress_total: 10 }),
    ],
  }),
  // Lo storico, a pagine (GET /api/uploads/history): la prima, di 41 in tutto.
  useUploadHistory: () => historyError ? {
    isPending: false, isError: true, error: historyError, data: undefined, isFetching: false, refetch: refetchHistory,
    hasNextPage: false, isFetchingNextPage: false, fetchNextPage,
  } : ({
    isPending: false,
    data: {
      pages: [{
        total: 41,
        next_before_id: 4,
        jobs: [
          job(4, 'done', { finished_at: '2026-09-30T10:00:00', targets: [
            { id: 1, tracker_label: 'ITT', action: 'upload', status: 'done' },
            { id: 2, tracker_label: 'Other', action: 'upload', status: 'failed' },
          ] }),
        ],
      }],
    },
    fetchNextPage,
    ...history,
  }),
  useHistoryFollowsQueue: () => undefined,
  useReorderQueue: () => ({ mutate: reorder, isPending: false }),
  useUpload: () => ({ data: undefined }),
  useDeleteUpload: () => ({ mutateAsync: remove, isPending: false }),
  useCancelUpload: () => ({ mutateAsync: cancel, isPending: false }),
}))
vi.mock('@/api/hooks/metadata', () => ({ posterUrl: () => '', useMetadataDetails: () => ({ data: undefined }) }))
vi.mock('@/components/AuthedPoster', () => ({ AuthedPoster: () => null }))

describe('UploadQueuePage', () => {
  it('lists what is running first, then the queue in order, and reorders it', () => {
    render(<MemoryRouter><UploadQueuePage /></MemoryRouter>)

    const titles = screen.getAllByText(/^Movie \d \(2024\)$/).map((el) => el.textContent)
    expect(titles).toEqual(['Movie 1 (2024)', 'Movie 2 (2024)', 'Movie 3 (2024)'])
    fireEvent.click(screen.getAllByTitle('Later in the queue')[0])
    expect(reorder).toHaveBeenCalledWith([3, 2], expect.anything())
  })

  it('opens an upload from its title with the keyboard too', () => {
    render(<MemoryRouter><UploadQueuePage /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Movie 1 (2024)' }).getAttribute('href')).toBe('/upload/1')
    cleanup()

    render(<MemoryRouter initialEntries={['/?tab=history']}><UploadQueuePage /></MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Movie 4 (2024)' })).toBeTruthy()
  })

  it('removes a history entry with two clicks on its trash button, without opening it', () => {
    render(<MemoryRouter initialEntries={['/?tab=history']}><UploadQueuePage /></MemoryRouter>)

    const button = screen.getByLabelText(/Remove from the history/)
    fireEvent.click(button)
    expect(remove).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Remove from the history/ }))
    expect(remove).toHaveBeenCalledWith(4)
  })

  it('cancels the running upload, and cancels then removes one waiting in the queue', async () => {
    render(<MemoryRouter><UploadQueuePage /></MemoryRouter>)
    remove.mockClear()

    const running = screen.getByRole('button', { name: 'Cancel the upload (it moves to the history)' })
    fireEvent.click(running)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel the upload (it moves to the history)' }))
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledWith(1))
    expect(remove).not.toHaveBeenCalled()

    const [queued] = screen.getAllByRole('button', { name: /Remove the upload/ })
    fireEvent.click(queued)
    fireEvent.click(screen.getAllByRole('button', { name: /Remove the upload/ })[0])
    await vi.waitFor(() => expect(remove).toHaveBeenCalledWith(2))
    expect(cancel).toHaveBeenCalledWith(2)
  })

  it('shows how many uploads the history holds and loads it a page at a time', () => {
    render(<MemoryRouter initialEntries={['/?tab=history']}><UploadQueuePage /></MemoryRouter>)

    expect(screen.getByText('History (41)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(fetchNextPage).toHaveBeenCalled()
  })

  it('keeps the queue when the history fails, and says so in its tab with a retry', () => {
    // Audit 2026-10-18 (R10): l'errore dello storico prendeva il posto di tutta la pagina.
    historyError = new Error('422 Unprocessable Entity')
    try {
      render(<MemoryRouter><UploadQueuePage /></MemoryRouter>)
      expect(screen.getByText('Movie 1 (2024)')).toBeTruthy()
      expect(screen.getByText('History')).toBeTruthy()
      cleanup()

      render(<MemoryRouter initialEntries={['/?tab=history']}><UploadQueuePage /></MemoryRouter>)
      expect(screen.getByText('The history could not be loaded: 422 Unprocessable Entity')).toBeTruthy()
      expect(screen.queryByText('No uploads yet.')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
      expect(refetchHistory).toHaveBeenCalled()
    } finally {
      historyError = null
    }
  })
})
