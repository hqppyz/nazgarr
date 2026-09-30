import { describe, expect, it } from 'vitest'

import {
  draftProblem,
  editDraft,
  effectiveDraft,
  eventMessage,
  fromForcedIds,
  missingEpisodes,
  newUploadLink,
  parseNewUploadParams,
  toForcedIds,
} from '@/lib/upload'

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

const source = {
  suggested_action: 'upload', proposed_name: 'Movie (2024) 1080p-GRP', category_id: 1, type_id: 4, resolution_id: 3,
  flags: { anonymous: false }, reseed_torrent_id: null, dupes: [{ torrent_id_remote: '9', verdict: 'identical' }],
}

describe('decision drafts', () => {
  it('follows the proposed values until the user touches a field', () => {
    const edited = editDraft(effectiveDraft(undefined, source), { name: 'Mine' })
    const refreshed = effectiveDraft(edited, { ...source, proposed_name: 'Movie (2024) 1080p-ME', type_id: 5 })
    expect(refreshed.name).toBe('Mine')
    expect(refreshed.type_id).toBe(5)
    expect(refreshed.reseed_torrent_id).toBe('9')
  })

  it('explains what is missing', () => {
    const draft = effectiveDraft(undefined, source)
    expect(draftProblem(draft)).toBeNull()
    expect(draftProblem({ ...draft, type_id: null })).toBe('upload.decision.problem.ids')
    expect(draftProblem({ ...draft, action: 'reseed', reseed_torrent_id: null })).toBe('upload.decision.problem.reseed')
    expect(draftProblem({ ...draft, action: 'skip', name: '' })).toBeNull()
  })
})

describe('new upload link from the poster view', () => {
  it('carries the source and the TMDB id, and reads them back', () => {
    const link = newUploadLink({ diskId: 2, path: 'media/TV/Show/Season 01', isDir: true }, 'tv/1399')
    expect(link).toBe('/upload/new?disk=2&path=media%2FTV%2FShow%2FSeason+01&dir=1&tmdb=tv%2F1399')

    const parsed = parseNewUploadParams(new URLSearchParams(link.split('?')[1]))
    expect(parsed).toEqual({ source: { diskId: 2, relativePath: 'media/TV/Show/Season 01', isDir: true }, tmdb: 'tv/1399' })
    expect(parseNewUploadParams(new URLSearchParams(''))).toEqual({ source: null, tmdb: '' })
  })
})
