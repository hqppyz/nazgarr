import { describe, expect, it } from 'vitest'

import type { TreeFileEntry } from '@/lib/fileTree'
import { DEFAULT_FILTERS, fileKey, filterFiles, formatBytes, summarizeByState } from '@/lib/library-filters'

function file(overrides: Partial<TreeFileEntry> & { relative_path: string }): TreeFileEntry {
  return { disk_id: 1, state: 'seeding', excluded: false, linked_paths: [], size_bytes: 0, ...overrides }
}

const FILES = [
  file({ relative_path: 'movies/Interstellar/Interstellar.mkv', size_bytes: 20e9 }),
  file({ relative_path: 'movies/Arrival/Arrival.mkv', size_bytes: 8e9, state: 'orphan_media' }),
  file({ relative_path: 'tv/Dark/S01E01.mkv', size_bytes: 2e9, excluded: true }),
]

const paths = (files: TreeFileEntry[]) => files.map((f) => f.relative_path)

describe('filterFiles', () => {
  it('hides excluded files unless showExcluded', () => {
    expect(filterFiles(FILES, DEFAULT_FILTERS)).toHaveLength(2)
    expect(filterFiles(FILES, { ...DEFAULT_FILTERS, showExcluded: true })).toHaveLength(3)
  })

  it('filters by exact state', () => {
    expect(paths(filterFiles(FILES, { ...DEFAULT_FILTERS, status: 'orphan_media' }))).toEqual([
      'movies/Arrival/Arrival.mkv',
    ])
  })

  it('searches case-insensitively on the whole path', () => {
    expect(paths(filterFiles(FILES, { ...DEFAULT_FILTERS, search: 'INTERSTELLAR' }))).toEqual([
      'movies/Interstellar/Interstellar.mkv',
    ])
    expect(filterFiles(FILES, { ...DEFAULT_FILTERS, search: 'movies/' })).toHaveLength(2)
  })

  it('applies an inclusive GB size range, ignoring blank or invalid bounds', () => {
    expect(paths(filterFiles(FILES, { ...DEFAULT_FILTERS, minGb: '10' }))).toEqual([
      'movies/Interstellar/Interstellar.mkv',
    ])
    expect(paths(filterFiles(FILES, { ...DEFAULT_FILTERS, maxGb: '8' }))).toEqual(['movies/Arrival/Arrival.mkv'])
    expect(filterFiles(FILES, { ...DEFAULT_FILTERS, minGb: '7,5', maxGb: '20' })).toHaveLength(2)
    expect(filterFiles(FILES, { ...DEFAULT_FILTERS, minGb: 'abc' })).toHaveLength(2)
  })

  it('keeps only duplicates, keyed by disk as well as path', () => {
    const keys = new Set([fileKey({ disk_id: 1, relative_path: 'movies/Arrival/Arrival.mkv' })])
    expect(paths(filterFiles(FILES, { ...DEFAULT_FILTERS, status: 'duplicates' }, keys))).toEqual([
      'movies/Arrival/Arrival.mkv',
    ])
    const otherDisk = new Set([fileKey({ disk_id: 2, relative_path: 'movies/Arrival/Arrival.mkv' })])
    expect(filterFiles(FILES, { ...DEFAULT_FILTERS, status: 'duplicates' }, otherDisk)).toHaveLength(0)
  })
})

describe('summarizeByState', () => {
  it('counts only non-excluded files, per state and in total', () => {
    const summary = summarizeByState(FILES)
    expect(summary.all).toEqual({ count: 2, size: 28e9 })
    expect(summary.seeding).toEqual({ count: 1, size: 20e9 })
    expect(summary.orphan_media).toEqual({ count: 1, size: 8e9 })
  })
})

describe('formatBytes', () => {
  it('uses decimal units with sensible precision', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1.5e9)).toBe('1.50 GB')
    expect(formatBytes(20e9)).toBe('20.0 GB')
    expect(formatBytes(350e9)).toBe('350 GB')
    expect(formatBytes(2.4e12)).toBe('2.40 TB')
  })
})

describe('excluded files are out of every check', () => {
  it('never appear under a state or duplicates tab, only in All with the toggle on', () => {
    const excludedDup = [file({ relative_path: 'x/sample.mkv', state: 'orphan_media', excluded: true })]
    const keys = new Set([fileKey(excludedDup[0])])
    expect(filterFiles(excludedDup, { ...DEFAULT_FILTERS, showExcluded: true, status: 'orphan_media' })).toHaveLength(0)
    expect(filterFiles(excludedDup, { ...DEFAULT_FILTERS, showExcluded: true, status: 'duplicates' }, keys)).toHaveLength(0)
    expect(filterFiles(excludedDup, { ...DEFAULT_FILTERS, showExcluded: true })).toHaveLength(1)
    expect(summarizeByState(excludedDup, keys).duplicates).toBeUndefined()
  })
})


describe('size units', () => {
  it('formats with binary units when chosen, and filters in GiB', async () => {
    const { setSizeUnits, formatBytes: fmt, filterFiles: filter, DEFAULT_FILTERS: defaults, gigabyteLabel } =
      await import('@/lib/library-filters')
    try {
      setSizeUnits('binary')
      expect(fmt(1536)).toBe('1.50 KiB')
      expect(fmt(20 * 1024 ** 3)).toBe('20.0 GiB')
      expect(gigabyteLabel()).toBe('GiB')
      const f = [file({ relative_path: 'a.mkv', size_bytes: 1.5 * 1024 ** 3 })]
      expect(filter(f, { ...defaults, minGb: '1.5' })).toHaveLength(1)
      expect(filter(f, { ...defaults, minGb: '1.6' })).toHaveLength(0)
    } finally {
      setSizeUnits('decimal')
    }
    expect(fmt(1500)).toBe('1.50 KB')
  })
})
