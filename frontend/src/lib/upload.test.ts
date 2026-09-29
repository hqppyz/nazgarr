import { describe, expect, it } from 'vitest'

import { eventMessage, fromForcedIds, missingEpisodes, toForcedIds } from '@/lib/upload'

describe('missingEpisodes', () => {
  it('lists the episodes TMDB expects that are not in the source', () => {
    expect(missingEpisodes([1, 2, 4], 5)).toEqual([3, 5])
    expect(missingEpisodes([1, 2, 3], 3)).toEqual([])
  })
})

describe('forced ids', () => {
  it('drops empty fields and keeps only numeric TVDB/MAL ids', () => {
    expect(toForcedIds({ tmdb: ' tv/1399 ', imdb: '', tvdb: '121361', mal: 'abc' })).toEqual({
      tmdb: 'tv/1399',
      imdb: undefined,
      tvdb: 121361,
      mal: undefined,
    })
  })

  it('round-trips what the backend stored', () => {
    expect(fromForcedIds({ tmdb: '603', tvdb: 5 })).toEqual({ tmdb: '603', imdb: '', tvdb: '5', mal: '' })
  })
})

describe('eventMessage', () => {
  it('uses the upload event sentence, then the error dictionary', () => {
    expect(eventMessage({ code: 'match_confirmed', params: { title: 'Dune', year: 2021 } })).toBe(
      'Match confirmed: Dune (2021).',
    )
    expect(eventMessage({ code: 'no_video_files', params: {} })).toBe('No video file found in the source.')
  })
})
