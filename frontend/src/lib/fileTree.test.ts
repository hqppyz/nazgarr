import { describe, expect, it } from 'vitest'

import { buildTree, type TreeFileEntry } from '@/lib/fileTree'

function file(overrides: Partial<TreeFileEntry> & { relative_path: string }): TreeFileEntry {
  return { state: 'seeding', excluded: false, linked_paths: [], size_bytes: 0, ...overrides }
}

describe('buildTree', () => {
  it('nests files under their folder path', () => {
    const tree = buildTree([file({ relative_path: 'movies/Interstellar/Interstellar.mkv' })])

    const movies = tree.children.get('movies')!
    const interstellar = movies.children.get('Interstellar')!
    const leaf = interstellar.children.get('Interstellar.mkv')!

    expect(movies.file).toBeNull()
    expect(interstellar.file).toBeNull()
    expect(leaf.file?.relative_path).toBe('movies/Interstellar/Interstellar.mkv')
  })

  it('groups multiple files under a shared parent folder', () => {
    const tree = buildTree([
      file({ relative_path: 'movies/A/a.mkv' }),
      file({ relative_path: 'movies/B/b.mkv' }),
    ])

    const movies = tree.children.get('movies')!
    expect([...movies.children.keys()]).toEqual(['A', 'B'])
  })

  it('handles a top-level file with no folder', () => {
    const tree = buildTree([file({ relative_path: 'readme.txt' })])
    expect(tree.children.get('readme.txt')?.file?.relative_path).toBe('readme.txt')
  })
})

describe('buildTree size aggregation', () => {
  it('sums sizes and file counts recursively up to the root', () => {
    const tree = buildTree([
      file({ relative_path: 'tv/Show/S01/e1.mkv', size_bytes: 100 }),
      file({ relative_path: 'tv/Show/S01/e2.mkv', size_bytes: 200 }),
      file({ relative_path: 'tv/Show/S02/e1.mkv', size_bytes: 50 }),
      file({ relative_path: 'movies/A/a.mkv', size_bytes: 1000 }),
    ])

    const show = tree.children.get('tv')!.children.get('Show')!
    expect(show.children.get('S01')!.sizeBytes).toBe(300)
    expect(show.sizeBytes).toBe(350)
    expect(show.fileCount).toBe(3)
    expect(tree.sizeBytes).toBe(1350)
    expect(tree.fileCount).toBe(4)
  })
})

