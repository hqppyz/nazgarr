import { describe, expect, it } from 'vitest'

import { episodeRanges, groupBySeason } from '@/lib/reviewGroups'

const episode = (id: number, episode: number, extra: Record<string, unknown> = {}) => ({
  id, direction: 'media_to_torrent', format: 'single', tracker_id: 1, tmdb_id: 1399, season_number: 1,
  episode_number: episode, ...extra,
})

describe('groupBySeason', () => {
  it('puts the single episodes of a season on one tracker together, in episode order', () => {
    const pack = episode(1, 1, { format: 'pack' })
    const movie = { id: 2, direction: 'media_to_torrent', format: 'single', tracker_id: 1, tmdb_id: 603 }
    const groups = groupBySeason([pack, episode(3, 2), movie, episode(4, 1), episode(5, 3, { tracker_id: 2 })])

    expect(groups.map((g) => g.map((r) => r.id))).toEqual([[1], [4, 3], [2], [5]])
  })
})

describe('episodeRanges', () => {
  it('writes consecutive episodes as a range', () => {
    expect(episodeRanges([7, 1, 2, 3, 4, 10, 9])).toBe('E01–E04, E07, E09–E10')
    expect(episodeRanges([5])).toBe('E05')
  })
})
