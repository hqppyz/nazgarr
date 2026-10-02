import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { MatchSummaryCard } from '@/components/upload/MatchSummaryCard'

const rematch = vi.fn()
vi.mock('@/api/hooks/uploads', () => ({ useRematch: () => ({ mutate: rematch, isPending: false }) }))
vi.mock('@/api/hooks/metadata', () => ({ posterUrl: () => '', useMetadataDetails: () => ({ data: undefined }) }))
vi.mock('@/components/AuthedPoster', () => ({ AuthedPoster: () => null }))
vi.mock('@/components/upload/MetadataLinks', () => ({ MetadataLinks: () => null }))

afterEach(cleanup)

const job = (extra = {}) => ({
  id: 4, status: 'awaiting_decision', title: 'The Matrix', year: 1999, tmdb_id: 603, content_type: 'movie',
  relative_path: 'releases/The.Matrix.1999.mkv', is_dir: false, kind: 'movie', seasons: [], episode: null,
  origin: 'watch', events: [{ code: 'auto_matched', params: { confidence: 0.97 } }], ...extra,
}) as unknown as UploadJob

describe('MatchSummaryCard', () => {
  it('says the match was automatic and lets you change it from the decision', () => {
    render(<MatchSummaryCard job={job()} />)

    expect(screen.getByText('Watched folder')).toBeTruthy()
    expect(screen.getByText('Matched automatically · 97%')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Change match/ }))
    expect(rematch).toHaveBeenCalled()
  })

  it('offers no rollback once the upload is approved', () => {
    render(<MatchSummaryCard job={job({ status: 'queued', origin: null, events: [] })} />)
    expect(screen.queryByRole('button', { name: /Change match/ })).toBeNull()
    expect(screen.queryByText('Watched folder')).toBeNull()
  })
})
