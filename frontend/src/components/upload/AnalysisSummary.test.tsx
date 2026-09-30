import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { UploadJob } from '@/api/hooks/uploads'
import { AnalysisSummary } from '@/components/upload/AnalysisSummary'
import { MetadataLinks } from '@/components/upload/MetadataLinks'

afterEach(cleanup)

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
