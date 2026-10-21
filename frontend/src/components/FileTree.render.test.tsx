import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FileTree } from '@/components/FileTree'
import type { TreeFileEntry } from '@/lib/fileTree'

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

    // I badge sono resi due volte (colonna Stato e, sotto sm, sotto il nome): si conta per riga.
    const row = screen.getByText('Gone.mkv').closest('tr')!
    expect(row.textContent).toContain('not in library')
    expect(screen.getByText('Relinkable.mkv').closest('tr')!.textContent).not.toContain('not in library')
  })
})
