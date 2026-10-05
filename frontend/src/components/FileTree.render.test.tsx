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

    // I badge sono resi due volte (colonna Stato e, sotto sm, sotto il nome): si conta per riga.
    const row = screen.getByText('Gone.mkv').closest('tr')!
    expect(row.textContent).toContain('not in library')
    expect(screen.getByText('Relinkable.mkv').closest('tr')!.textContent).not.toContain('not in library')
  })
})

describe('FileTree incremental rendering', () => {
  it('renders the rows in blocks and adds the next block when the end comes into view', async () => {
    const { act } = await import('@testing-library/react')
    const callbacks: IntersectionObserverCallback[] = []
    class FakeObserver {
      constructor(cb: IntersectionObserverCallback) {
        callbacks.push(cb)
      }
      observe() {}
      disconnect() {}
    }
    const original = globalThis.IntersectionObserver
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver
    try {
      const files = Array.from({ length: 700 }, (_, i) => file(`f${String(i).padStart(4, '0')}.mkv`, {}))
      const { container } = render(<FileTree expandAll files={files} />)
      const fileRows = () => container.querySelectorAll('tbody tr:not([aria-hidden])').length
      expect(fileRows()).toBe(300)

      act(() => callbacks.at(-1)!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
      expect(fileRows()).toBe(600)
      act(() => callbacks.at(-1)!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver))
      expect(fileRows()).toBe(700)
      expect(container.querySelector('tbody tr[aria-hidden]')).toBeNull()
    } finally {
      globalThis.IntersectionObserver = original
    }
  })
})
