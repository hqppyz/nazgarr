import { describe, expect, it } from 'vitest'

import { toCards } from '@/pages/library/posterCards'

const file = (state: string, excluded = false) => ({
  media_file_id: 1, disk_id: 1, relative_path: 'x.mkv', size_bytes: 10, state, excluded, linked_paths: [],
  duplicate: false, in_review: false, stopped: false,
})
const item = (tmdbId: number, files: ReturnType<typeof file>[]) => ({
  id: tmdbId, content_type: 'movie', tmdb_id: tmdbId, season_number: null, episode_number: null,
  has_poster: false, title: `Movie ${tmdbId}`, year: 2001, files,
})

describe('toCards', () => {
  it('leaves out titles whose files are all excluded, so Total = Seeding + Orphaned', () => {
    const cards = toCards([
      item(1, [file('seeding')]),
      item(2, [file('orphan_media')]),
      item(3, [file('seeding', true)]),
    ])
    expect(cards.map((c) => c.tmdb_id)).toEqual([1, 2])
  })
})
