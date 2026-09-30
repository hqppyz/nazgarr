import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Schemas } from '@/api/client'
import { TrackerOverview } from '@/pages/library/TrackerOverview'

const navigate = vi.fn()
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }))
vi.mock('@/pages/config/ServiceIcons', () => ({ TrackerLogo: () => null }))

afterEach(cleanup)

const entry = { media_file_id: 1, season_number: null, episode_number: null, seed_path: 'torrents/public/M.mkv',
  client: 'qbit public', client_enabled: false, state: 'stalledUP', torrent: 'M' }

const detail = {
  content_type: 'movie', tmdb_id: 603,
  files: [{ disk_id: 1, relative_path: 'media/M/M.mkv', is_video: true, excluded: false }],
  trackers: [
    { tracker_id: 3, label: 'ITT', configured: true, has_upload_profile: true, seeding: 0, total: 1, entries: [] },
    { tracker_id: null, label: 'tracker.torrent.eu.org', configured: false, has_upload_profile: false, seeding: 1,
      total: 1, entries: [entry] },
  ],
} as unknown as Schemas['ItemDetailResponse']

describe('TrackerOverview', () => {
  it('shows each tracker with its coverage, the paths on demand and an upload where it is missing', () => {
    render(<TrackerOverview detail={detail} />)

    expect(screen.getByText('0/1 seeding')).toBeTruthy()
    expect(screen.getByText('client disabled')).toBeTruthy()
    expect(screen.queryByText('torrents/public/M.mkv')).toBeNull()
    fireEvent.click(screen.getByText('tracker.torrent.eu.org'))
    expect(screen.getByText('torrents/public/M.mkv')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Upload \/ reseed to ITT/ }))
    expect(navigate).toHaveBeenCalledWith('/upload/new?disk=1&path=media%2FM%2FM.mkv&tmdb=movie%2F603&trackers=3')
  })
})
