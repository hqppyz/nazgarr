import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NotImportedView } from '@/pages/torrent/NotImportedView'

const remove = vi.fn()

const torrent = (id: number, category: string, name: string, extra = {}) => ({
  client_torrent_id: id, name, info_hash: `h${id}`, client: 'qbit', tracker: 'tracker.example', category,
  detail: 'why', matched_by: 'arr', content_type: null, tmdb_id: null, title: null, year: null,
  season_number: null, episode_number: null, quality: '1080p', replaced_by: null, total_bytes: 1e9,
  video_bytes: 1e9, file_count: 2, ratio: 1.5, seeding_time_seconds: 3 * 86_400, added_at: null, state: 'uploading',
  seed_requirement: { status: 'unknown_tracker', remaining: {} },
  removal_warnings: [],
  ...extra,
})

vi.mock('@/api/hooks/library', () => ({
  useRefreshNotImported: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveNotImported: () => ({ mutate: remove, isPending: false }),
  useNotImported: () => ({
    isPending: false,
    data: {
      classified: true, computed_at: '2026-09-29T10:00:00Z', with_arr: true, excluded_count: 1,
      summary: { superseded: { count: 1, total_bytes: 1e9 }, never_imported: { count: 1, total_bytes: 1e9 } },
      torrents: [
        torrent(1, 'superseded', 'Old.Movie.1080p.mkv', {
          replaced_by: { relative_path: 'media/movies/Old Movie (2001)/Old.Movie.2160p.mkv', size_bytes: 5e10, quality: '2160p' },
          seed_requirement: { status: 'met', tracker_label: 'T', min_seed_time_seconds: 3 * 86_400, min_ratio: null, rule: 'any', remaining: {} },
        }),
        torrent(2, 'never_imported', 'Random.Download.mkv', {
          seed_requirement: {
            status: 'pending', tracker_label: 'T', min_seed_time_seconds: 7 * 86_400, min_ratio: null, rule: 'any',
            remaining: { seed_time_seconds: 4 * 86_400 },
          },
        }),
        // Requisito soddisfatto, ma i file li usa anche un altro torrent.
        torrent(4, 'never_imported', 'Shared.Files.mkv', {
          seed_requirement: { status: 'met', tracker_label: 'T', min_seed_time_seconds: 86_400, min_ratio: null, rule: 'any', remaining: {} },
          removal_warnings: [{ code: 'shared_files', params: { count: 1, torrents: 'Twin' } }],
        }),
        // Da una cache di prima del campo: senza seed_requirement non deve rompersi.
        torrent(3, 'never_imported', 'Excluded.Sample.mkv', { excluded: true, seed_requirement: undefined }),
      ],
    },
  }),
}))
vi.mock('@/pages/library/ItemDetailSheet', () => ({ ItemDetailSheet: () => null }))

afterEach(cleanup)

describe('NotImportedView', () => {
  it('shows each torrent with its reason and what replaced it, filterable by category', () => {
    render(<MemoryRouter><NotImportedView /></MemoryRouter>)

    expect(screen.getByText('Old.Movie.2160p.mkv')).toBeTruthy()
    expect(screen.getByText('Random.Download.mkv')).toBeTruthy()

    expect(screen.queryByText('Excluded.Sample.mkv')).toBeNull()  // esclusi nascosti di default
    fireEvent.click(screen.getByRole('button', { name: /Excluded/ }))
    expect(screen.getByText('Excluded.Sample.mkv')).toBeTruthy()

    fireEvent.click(screen.getAllByText('Superseded')[0])
    expect(screen.queryByText('Random.Download.mkv')).toBeNull()
    expect(screen.getByText('3d')).toBeTruthy()
  })

  it("says which torrents met their tracker's seeding requirement, and filters them", () => {
    render(<MemoryRouter><NotImportedView /></MemoryRouter>)

    // "OK" per entrambi, il secondo con il problema in più nel popover.
    expect(screen.getAllByText('OK')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Check before removing (1)' })).toBeTruthy()
    expect(screen.getByText('4d left')).toBeTruthy()
    // Senza rischi solo quello senza altri problemi.
    fireEvent.click(screen.getByRole('button', { name: /Safe to remove \(1\)/ }))
    expect(screen.queryByText('Random.Download.mkv')).toBeNull()
    expect(screen.queryByText('Shared.Files.mkv')).toBeNull()
    expect(screen.getByText('Old.Movie.1080p.mkv')).toBeTruthy()
  })

  it('offers removal only where the requirement is met and nothing blocks it, after a confirmation', () => {
    render(<MemoryRouter><NotImportedView /></MemoryRouter>)

    // Old.Movie sì; Shared.Files no (i file servono a un altro torrent); gli altri non hanno l'OK.
    const buttons = screen.getAllByRole('button', { name: 'Remove from the client…' })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])
    expect(screen.getByText('Remove the torrent and its files?')).toBeTruthy()
    expect(remove).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Remove and delete the files' }))
    expect(remove).toHaveBeenCalledWith(1, expect.anything())
  })
})
