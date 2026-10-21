import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { FileTree, type TreeRowActions } from '@/components/FileTree'
import type { TreeFileEntry } from '@/lib/fileTree'

const file = (relative_path: string, overrides: Partial<TreeFileEntry> = {}): TreeFileEntry => ({
  relative_path, state: 'orphan_media', excluded: false, linked_paths: [], size_bytes: 1, ...overrides,
})

function menuActions() {
  const picked: string[] = []
  const actions: TreeRowActions = {
    file: vi.fn((f: TreeFileEntry) => [{ label: 'Exclude file', onSelect: () => picked.push(f.relative_path) }]),
    folder: vi.fn((node) => [{ label: 'Exclude folder', onSelect: () => picked.push(node.path) }]),
  }
  return { actions, picked }
}

describe('FileTree menus', () => {
  it('builds the menu of a row only when it opens, with that row', async () => {
    const { actions, picked } = menuActions()
    render(<FileTree expandAll actions={actions} files={[file('Movies/A.mkv'), file('Movies/B.mkv')]} />)
    expect(actions.file).not.toHaveBeenCalled() // niente voci calcolate per riga al render

    fireEvent.contextMenu(screen.getByText('B.mkv'))
    fireEvent.click(await screen.findByText('Exclude file'))
    expect(picked).toEqual(['Movies/B.mkv'])
  })

  it('opens the same menu from the row button, for touch', async () => {
    const { actions, picked } = menuActions()
    render(<FileTree expandAll actions={actions} files={[file('Movies/A.mkv')]} />)
    const buttons = screen.getAllByRole('button', { name: 'More actions' })
    fireEvent.click(buttons[0]) // la cartella Movies
    fireEvent.click(await screen.findByText('Exclude folder'))
    expect(picked).toEqual(['Movies'])
  })

  it('shows the hardlinked paths of a file', async () => {
    render(<FileTree expandAll files={[file('Movies/A.mkv', { linked_paths: ['torrents/A.mkv'] })]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Hardlink' }))
    expect(await screen.findByText('torrents/A.mkv')).toBeTruthy()
  })
})

describe('FileTree keyboard', () => {
  it('opens and closes a folder from its name button', () => {
    render(<FileTree files={[file('Movies/Old/A.mkv')]} />)
    const folder = screen.getByRole('button', { name: /Old/ })
    expect(folder.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(folder)
    expect(screen.getByRole('button', { name: /Old/ }).getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText('A.mkv')).toBeTruthy()
  })

  it('opens the detail of a file from its name button', () => {
    const onOpenFile = vi.fn()
    render(
      <FileTree expandAll onOpenFile={onOpenFile}
                files={[file('Movies/A.mkv', { content_type: 'movie', tmdb_id: 603 }), file('Movies/notes.nfo')]} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'A.mkv' }))
    expect(onOpenFile).toHaveBeenCalledWith(expect.objectContaining({ relative_path: 'Movies/A.mkv' }))
    // Senza identità non c'è niente da aprire: niente pulsante.
    expect(screen.queryByRole('button', { name: 'notes.nfo' })).toBeNull()
  })
})
