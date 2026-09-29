import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { NotImportedView } from '@/pages/torrent/NotImportedView'

const torrent = (id: number, category: string, name: string, extra = {}) => ({
  client_torrent_id: id, name, info_hash: `h${id}`, client: 'qbit', tracker: 'tracker.example', category,
  detail: 'why', matched_by: 'arr', content_type: null, tmdb_id: null, title: null, year: null,
  season_number: null, episode_number: null, quality: '1080p', replaced_by: null, total_bytes: 1e9,
  video_bytes: 1e9, file_count: 2, ratio: 1.5, seeding_time_seconds: 3 * 86_400, added_at: null, state: 'uploading',
  ...extra,
})

vi.mock('@/api/hooks/library', () => ({
  useNotImported: () => ({
    isPending: false,
    data: {
      classified: true,
      summary: { superseded: { count: 1, total_bytes: 1e9 }, never_imported: { count: 1, total_bytes: 1e9 } },
      torrents: [
        torrent(1, 'superseded', 'Old.Movie.1080p.mkv', {
          replaced_by: { relative_path: 'media/movies/Old Movie (2001)/Old.Movie.2160p.mkv', size_bytes: 5e10, quality: '2160p' },
        }),
        torrent(2, 'never_imported', 'Random.Download.mkv'),
      ],
    },
  }),
}))
vi.mock('@/pages/library/ItemDetailSheet', () => ({ ItemDetailSheet: () => null }))

describe('NotImportedView', () => {
  it('shows each torrent with its reason and what replaced it, filterable by category', () => {
    render(<MemoryRouter><NotImportedView /></MemoryRouter>)

    expect(screen.getByText('Old.Movie.2160p.mkv')).toBeTruthy()
    expect(screen.getByText('Random.Download.mkv')).toBeTruthy()

    fireEvent.click(screen.getAllByText('Superseded')[0])
    expect(screen.queryByText('Random.Download.mkv')).toBeNull()
    expect(screen.getByText('3d')).toBeTruthy()
  })
})
