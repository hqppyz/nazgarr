import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Seasons } from '@/pages/library/ItemDetailSheet'
import type { PackSelection } from '@/lib/pack'

const episode = (n: number, refs: number[][]) => ({ number: n, titles: [`Capitolo ${n}`], air_date: null, refs })
const tmdb = {
  key: 'tmdb:default', label: 'TMDB', source: 'tmdb',
  seasons: [{ season_number: 1, episodes: Array.from({ length: 10 }, (_, i) => episode(i + 1, [[1, i + 1]])) }],
}
const parts = {
  key: 'tmdb:group:g1', label: 'TMDB · Parts', source: 'tmdb',
  seasons: [
    { season_number: 1, episodes: [1, 2, 3, 4, 5].map((n) => episode(n, [[1, n]])) },
    { season_number: 2, episodes: [1, 2, 3, 4, 5].map((n) => episode(n, [[1, n + 5]])) },
  ],
}

vi.mock('@/api/hooks/library', () => ({
  useLibraryEpisodeOrders: () => ({
    data: { orders: [tmdb, parts], recommended: 'tmdb:default', files_order: 'tmdb:default', fits: {}, warning: null, found: {} },
  }),
  useExcludeFile: () => ({ mutate: vi.fn(), isPending: false }),
  useItemDetail: () => ({ data: undefined }),
  useSearchNow: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('@/api/hooks/reviews', () => ({
  useApproveReview: () => ({ mutate: vi.fn() }), useRejectReview: () => ({ mutate: vi.fn() }),
  useReconcileNow: () => ({ mutate: vi.fn() }),
}))

afterEach(cleanup)

const files = [6, 7].map((e) => ({
  media_file_id: e, season_number: 1, episode_number: e, disk_id: 1, is_video: true, excluded: false,
  relative_path: `media/Lupin/Season 01/Lupin - S01E0${e}.mkv`, size_bytes: 1, state: 'orphan_media',
  stopped: false, hardlinks: [], duplicates: [], in_review: false,
}))
const selection = { active: false, has: () => false, pick: vi.fn(), setMany: vi.fn() } as unknown as PackSelection

describe('Seasons', () => {
  it('shows the series in another episode ordering, with its numbers and titles', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Seasons files={files as never} uploadTmdb="tv/96677" selection={selection} tmdbId={96677} />
      </MemoryRouter>,
    )
    // Di default la numerazione dei file, con i titoli dell'ordinamento.
    expect(screen.getByText('Season 1')).toBeTruthy()
    expect(screen.getByText(/10 expected/)).toBeTruthy()

    await user.click(screen.getByRole('combobox'))
    await user.click(await screen.findByRole('option', { name: /TMDB · Parts/ }))
    // Nelle "parti" gli episodi 6 e 7 sono la stagione 2, episodi 1 e 2.
    expect(await screen.findByText('Season 2')).toBeTruthy()
    fireEvent.click(screen.getByText('Season 2'))
    expect(screen.getByText('S02E01')).toBeTruthy()
    expect(screen.getByText('Capitolo 1')).toBeTruthy()
  })
})
