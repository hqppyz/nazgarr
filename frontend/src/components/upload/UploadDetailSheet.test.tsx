import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { UploadDetailSheet } from '@/components/upload/UploadDetailSheet'

const job = {
  id: 7, title: 'Movie', year: 2024, kind: 'movie', status: 'done', relative_path: 'Movies/Movie (2024)',
  tmdb_id: null, content_type: 'movie', poster_path: null, seasons: [], episode: null, analysis: null,
  created_at: null, finished_at: null, mediainfo_text: null, screenshot_urls: [], descriptions: {}, events: [],
  targets: [
    { id: 1, tracker_label: 'ITT', action: 'reseed', status: 'done', approved_name: null, info_hash: null,
      remote_url: null, error_message: 'seed_recheck_pending', dupes: [] },
    { id: 2, tracker_label: 'Other', action: 'upload', status: 'failed', approved_name: null, info_hash: null,
      remote_url: null, error_message: 'rejected', dupes: [] },
  ],
} as unknown as UploadJob

vi.mock('@/api/hooks/uploads', () => ({ useUpload: () => ({ data: job }) }))
vi.mock('@/api/hooks/metadata', () => ({ posterUrl: () => '', useMetadataDetails: () => ({ data: undefined }) }))
vi.mock('@/components/upload/RetryUploadButton', () => ({ RetryUploadButton: () => null }))
vi.mock('@/components/upload/DeleteUploadButton', () => ({ DeleteUploadButton: () => null }))
vi.mock('@/components/upload/MediaInfoPreview', () => ({ MediaInfoPreview: () => null }))

describe('UploadDetailSheet', () => {
  it("shows a published tracker's pending recheck as a translated warning, a failure as an error", () => {
    render(<UploadDetailSheet uploadId={7} onClose={() => {}} />)

    const pending = screen.getByText(/stopped until its recheck passes/)
    expect(pending.className).toContain('text-amber-600')
    expect(screen.queryByText('seed_recheck_pending')).toBeNull()
    expect(screen.getByText('rejected').className).toContain('text-red-600')
  })
})
