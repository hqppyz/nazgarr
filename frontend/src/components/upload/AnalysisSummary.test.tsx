import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { AnalysisSummary } from '@/components/upload/AnalysisSummary'
import { MetadataLinks } from '@/components/upload/MetadataLinks'

const episode = (n: number) => ({
  client: 'qBit', name: `Show.S01E0${n}.mkv`, info_hash: `h${n}`, tracker_host: 'itatorrents.xyz', state: 'uploading',
  match: n === 1 ? 'hardlink' : 'same_size', videos_matched: 1, videos_total: 8,
})

describe('AnalysisSummary', () => {
  it('sums up many episodes in one line per client and tracker, the list only on demand', () => {
    const job = {
      analysis: {
        total_size_bytes: 1e10, file_count: 8, arr_grabs: [
          { tracker_host: 'itatorrents.xyz', torrent_id_remote: '1', indexer: 'ITT' },
          { tracker_host: 'itatorrents.xyz', torrent_id_remote: '2', indexer: 'ITT' },
        ],
        client_matches: [1, 2, 3].map(episode),
      },
    } as unknown as UploadJob

    render(<AnalysisSummary job={job} />)

    expect(screen.getByText('Radarr/Sonarr downloaded this from ITT (2 torrent(s)): probably not your own release.')).toBeTruthy()
    const recap = 'Already seeding on qBit for itatorrents.xyz: 3 torrent(s), 1 with these very files.'
    expect(screen.queryByText('Show.S01E02.mkv')).toBeNull()
    fireEvent.click(screen.getByText(recap))
    expect(screen.getByText('Show.S01E02.mkv')).toBeTruthy()
  })

  it('says when another upload not finished has the same files, with a link to it', () => {
    // Audit 2026-10-18 (finding 163): due upload vivi sugli stessi file arrivavano alla decisione in silenzio.
    const job = {
      analysis: {
        total_size_bytes: 1, file_count: 1, arr_grabs: [], client_matches: [],
        other_jobs: [{ id: 12, status: 'awaiting_decision', kind: 'season_pack', title: 'Show', seasons: [1], episode: null, videos: 8 }],
      },
    } as unknown as UploadJob

    render(<AnalysisSummary job={job} />, { wrapper: MemoryRouter })

    expect(screen.queryByText(/Not on any client/)).toBeNull()
    fireEvent.click(screen.getByText(/Other uploads not finished yet with these same files: 1\./))
    expect(screen.getByRole('link', { name: '#12 Show' }).getAttribute('href')).toBe('/upload/12')
    expect(screen.getByText('Review and approve, 8 video(s) in common')).toBeTruthy()
  })
})

describe('MetadataLinks', () => {
  it('links every known id to its service', () => {
    const job = { content_type: 'tv', tmdb_id: 95396, imdb_id: 'tt11280740', tvdb_id: 371980, mal_id: null } as unknown as UploadJob

    render(<MetadataLinks job={job} />)

    expect(screen.getByTitle('TMDB').getAttribute('href')).toBe('https://www.themoviedb.org/tv/95396')
    expect(screen.getByTitle('IMDb').getAttribute('href')).toBe('https://www.imdb.com/title/tt11280740/')
    expect(screen.getByTitle('TVDB').getAttribute('href')).toBe('https://thetvdb.com/dereferrer/series/371980')
    expect(screen.queryByTitle('MyAnimeList')).toBeNull()
  })
})
