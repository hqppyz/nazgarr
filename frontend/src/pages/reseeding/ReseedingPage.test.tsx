import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ReseedingPage } from '@/pages/reseeding/ReseedingPage'

const approve = vi.fn()
const reject = vi.fn()
const fetchNextPage = vi.fn()
let reviews: unknown[] = []
let hasNextPage = false

const review = (id: number, name: string) => ({
  id, candidate_name: name, direction: 'media_to_torrent', confidence: 0.97, ambiguity_reason: null,
  status: 'pending', format: 'single', tracker_id: 1, tracker: 'T', tmdb_id: id, season_number: null,
  episode_number: null, media_item_id: id, layout: null, verify_status: null, seeding_on: [], seeding_here: [],
  torrent_client_id: null, client_category: null, client_tags: null,
})

vi.mock('@/api/hooks/reviews', () => ({
  useReviewQueue: () => ({
    data: { pages: [{ items: reviews, total: reviews.length, offset: 0, next_offset: hasNextPage ? reviews.length : null }] },
    isPending: false, hasNextPage, isFetchingNextPage: false, fetchNextPage,
  }),
  useApproveReview: () => ({ mutate: approve, isPending: false }),
  useRejectReview: () => ({ mutate: reject, isPending: false }),
  useDecideReviews: () => ({ mutate: vi.fn(), isPending: false }),
  useCandidateAudit: () => ({ data: [], isPending: false }),
  useSetReviewClientLabels: () => ({ mutate: vi.fn(), isPending: false }),
  useRecentSeedJobs: () => ({ data: [], isPending: false }),
  useRetryFailed: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSeedJob: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('@/api/hooks/fullChecks', () => ({ useFullCheck: () => ({ data: undefined }) }))
vi.mock('@/api/hooks/torrentClients', () => ({ useTorrentClientCategories: () => ({ data: undefined }) }))

describe('ReseedingPage review queue', () => {
  it('approves and rejects the review of the row clicked', () => {
    reviews = [review(1, 'First.Movie.mkv'), review(2, 'Second.Movie.mkv')]
    render(<ReseedingPage />)
    const approveButtons = screen.getAllByRole('button', { name: 'Approve' })
    fireEvent.click(approveButtons[1])
    expect(approve).toHaveBeenCalledWith(2)
    fireEvent.click(screen.getAllByRole('button', { name: 'Reject' })[0])
    expect(reject).toHaveBeenCalledWith(1)
  })

  it('asks the server for the next page when the end of the queue comes into view', () => {
    const observed: IntersectionObserverCallback[] = []
    class FakeObserver {
      constructor(callback: IntersectionObserverCallback) {
        observed.push(callback)
      }
      observe() {}
      disconnect() {}
    }
    const original = globalThis.IntersectionObserver
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
    try {
      reviews = Array.from({ length: 100 }, (_, i) => review(i + 1, `Movie.${i}.mkv`))
      hasNextPage = true
      render(<ReseedingPage />)
      // Tutta la pagina ricevuta, e il totale della coda in testa.
      expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(100)
      expect(screen.getByText('100 waiting for a decision')).toBeTruthy()
      observed.at(-1)?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
      expect(fetchNextPage).toHaveBeenCalledTimes(1)
    } finally {
      globalThis.IntersectionObserver = original
      hasNextPage = false
    }
  })
})
