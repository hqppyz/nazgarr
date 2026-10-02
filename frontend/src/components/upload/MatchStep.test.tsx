import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { MatchStep } from '@/components/upload/MatchStep'

const confirm = vi.fn()

vi.mock('@/api/hooks/settings', () => ({ useSetting: () => ({ data: undefined }) }))
vi.mock('@/api/hooks/uploads', () => ({
  useConfirmMatch: () => ({ mutate: confirm, isPending: false }),
  useReidentify: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('@/api/hooks/metadata', () => ({
  posterUrl: () => '/poster.jpg',
  useMetadataSearch: () => ({ data: undefined, isFetching: false, isError: false }),
  useMetadataDetails: (contentType: string | null) => ({
    isPending: false,
    data:
      contentType === 'tv'
        ? {
            tmdb_id: 95396, content_type: 'tv', title: 'Severance', year: 2022, poster_path: null, genres: ['Drama'],
            runtime: 50, imdb_id: 'tt11280740', tvdb_id: 371980, cast: ['Adam Scott'], original_language: 'en',
            seasons: [
              { season_number: 1, name: 'Season 1', episode_count: 9, air_date: null },
              { season_number: 2, name: 'Season 2', episode_count: 10, air_date: null },
            ],
          }
        : undefined,
  }),
}))
vi.mock('@/components/AuthedPoster', () => ({ AuthedPoster: () => null }))

const job = {
  id: 7, status: 'awaiting_match', kind: 'season_pack', is_dir: true, content_type: 'tv', title: 'Severance',
  year: 2022, seasons: [2], episode: null, forced_ids: {},
  candidates: [
    { tmdb_id: 95396, content_type: 'tv', title: 'Severance', year: 2022, poster_path: null, source: 'sonarr' },
    { tmdb_id: 1, content_type: 'movie', title: 'Severance', year: 2006, poster_path: null, source: 'search' },
  ],
  layout: {
    kind: 'season_pack', seasons: [2], episodes_by_season: { '2': [1, 2, 3, 5, 6] },
    videos: [1, 2, 3, 5, 6].map((e) => ({ relative_path: `S02E0${e}.mkv`, size_bytes: 1, season: 2, episodes: [e] })),
  },
} as unknown as UploadJob

afterEach(() => {
  cleanup()
  confirm.mockClear()
})

describe('MatchStep', () => {
  it('suggests the first candidate, compares episodes with TMDB and confirms the season pack', () => {
    render(<MatchStep job={job} />)

    expect(screen.getByText('Sonarr')).toBeTruthy()
    expect(screen.getByText('5/10 episodes')).toBeTruthy()
    expect(screen.getByText('5 missing')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    expect(confirm).toHaveBeenCalledWith(
      { content_type: 'tv', tmdb_id: 95396, kind: 'season_pack', seasons: [2], episode: null },
      expect.anything(),
    )
  })

  it('switches to a movie candidate and sends it as a movie', () => {
    render(<MatchStep job={job} />)

    fireEvent.click(screen.getAllByRole('button', { pressed: false })[0])
    expect(screen.getByText('The files look like episodes of a series, but a movie is selected.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    expect(confirm.mock.calls[0][0]).toMatchObject({ content_type: 'movie', tmdb_id: 1, kind: 'movie', seasons: [] })
  })

  it('says how sure the best match is against the automatic threshold, and why', () => {
    const scored = {
      ...job,
      candidates: [
        { ...job.candidates[0], source: 'search', confidence: 0.85,
          confidence_parts: { basis: 'name', title: 1, title_guess: 'Severance', title_matched: 'Severance', year: 0.85,
            year_guess: 2021, year_candidate: 2022, type: 1, type_guess: 'tv', type_candidate: 'tv' } },
        job.candidates[1],
      ],
    } as unknown as UploadJob
    render(<MatchStep job={scored} />)

    // Nel dettaglio del candidato scelto, sotto i link: niente riquadro sopra la griglia.
    expect(screen.getByText(/Reliability 85%\./)).toBeTruthy()
    expect(screen.getByText(/Below the automatic match threshold \(90%\)/)).toBeTruthy()
    // Fattore per fattore, con il motivo, e il prodotto.
    expect(screen.getByText('file 2021, TMDB 2022: one year apart (often release vs. name)')).toBeTruthy()
    expect(screen.getByText('"Severance" from the file, closest TMDB title "Severance"')).toBeTruthy()
    expect(screen.getByText('100% × 85% × 100% = 85%')).toBeTruthy()
    expect(screen.queryByText(/Best match/)).toBeNull()
  })
})
