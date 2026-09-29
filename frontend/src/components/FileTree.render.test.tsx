import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FileTree, type TreeFileEntry } from '@/components/FileTree'

const file = (relative_path: string, overrides: Partial<TreeFileEntry>): TreeFileEntry => ({
  relative_path, state: 'orphan_torrent', excluded: false, linked_paths: [], size_bytes: 1, ...overrides,
})

describe('FileTree badges', () => {
  it('marks an orphaned torrent file with no library hardlink as "not in library"', () => {
    render(
      <FileTree
        expandAll
        files={[
          file('torrents/Gone.mkv', {}),
          file('torrents/Relinkable.mkv', { linked_paths: ['media/Relinkable.mkv'] }),
        ]}
      />,
    )

    expect(screen.getAllByText('not in library')).toHaveLength(1)
    const row = screen.getByText('Gone.mkv').closest('tr')!
    expect(row.textContent).toContain('not in library')
  })
})
