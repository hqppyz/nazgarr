import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FileTree, type TreeRowActions } from '@/components/FileTree'
import type { TreeFileEntry } from '@/lib/fileTree'
import { usePackSelection } from '@/lib/pack'

// jsdom non ha layout: l'area che scorre, il <tbody> e le righe hanno qui
// misure finte, coerenti con lo scroll. Sopra le righe 40 px (l'intestazione
// della tabella), la vista è alta 400 px.
const HEADER = 40
const VIEWPORT = 400

const rect = (top: number, height: number) =>
  ({ top, height, bottom: top + height, left: 0, right: 800, width: 800, x: 0, y: top, toJSON: () => ({}) }) as DOMRect

let scrollTop = 0
let rowHeight: (key: string) => number = () => 20
let root: HTMLDivElement

beforeEach(() => {
  scrollTop = 0
  rowHeight = () => 20
  root = document.createElement('div')
  root.setAttribute('data-scroll-root', '')
  document.body.appendChild(root)
  Object.defineProperty(root, 'clientHeight', { configurable: true, get: () => VIEWPORT })
  Object.defineProperty(root, 'scrollTop', {
    configurable: true,
    get: () => scrollTop,
    set: (value: number) => {
      scrollTop = value
    },
  })
  root.getBoundingClientRect = () => rect(0, VIEWPORT)
  vi.spyOn(HTMLTableSectionElement.prototype, 'getBoundingClientRect').mockImplementation(() => rect(HEADER - scrollTop, 0))
  vi.spyOn(HTMLTableRowElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLTableRowElement) {
    const key = this.getAttribute('data-row-key')
    return rect(0, key === null ? 0 : rowHeight(key))
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  root.remove()
})

const file = (relative_path: string, overrides: Partial<TreeFileEntry> = {}): TreeFileEntry => ({
  relative_path, state: 'orphan_media', excluded: false, linked_paths: [], size_bytes: 1, disk_id: 1, ...overrides,
})
const name = (i: number) => `f${String(i).padStart(4, '0')}.mkv`
const many = (n: number, overrides: Partial<TreeFileEntry> = {}) => Array.from({ length: n }, (_, i) => file(name(i), overrides))

const actions: TreeRowActions = {
  file: () => [{ label: 'Exclude file', onSelect: () => {} }],
  folder: () => [{ label: 'Exclude folder', onSelect: () => {} }],
}

function renderTree(ui: React.ReactElement) {
  return render(ui, { container: root.appendChild(document.createElement('div')) })
}

function scrollTo(y: number) {
  act(() => {
    scrollTop = y
    root.dispatchEvent(new Event('scroll'))
  })
}

const rowOf = (path: string) => root.querySelector(`tr[data-row-key="${path}"]`)
const mounted = () => Array.from(root.querySelectorAll('tbody tr[data-row-key]')).map((row) => row.getAttribute('data-row-key'))

// Dove comincia una riga montata, in coordinate della lista: gli spazi e le
// righe che la precedono nel <tbody>.
function listOffsetOf(path: string): number {
  let offset = 0
  for (const row of Array.from(root.querySelectorAll('tbody > tr'))) {
    const key = row.getAttribute('data-row-key')
    if (key === path) return offset
    offset += key === null ? parseFloat((row as HTMLElement).style.height) : rowHeight(key)
  }
  throw new Error(`${path} non è montata`)
}

describe('FileTree window', () => {
  it('mounts only the rows near the view, with the space of the others, and follows the scroll', () => {
    renderTree(<FileTree expandAll files={many(1000)} />)
    expect(rowOf(name(0))).not.toBeNull()
    expect(rowOf(name(500))).toBeNull()
    expect(mounted().length).toBeLessThan(100)

    scrollTo(HEADER + 500 * 20) // la riga 500 in cima alla vista
    expect(rowOf(name(500))).not.toBeNull()
    expect(rowOf(name(0))).toBeNull()
    expect(mounted().length).toBeLessThan(200)
    // Ogni riga al suo posto, l'altezza è quella dell'albero intero.
    expect(listOffsetOf(name(500))).toBe(500 * 20)
    const gaps = Array.from(root.querySelectorAll<HTMLElement>('tbody > tr[data-row-gap]'))
    const total = gaps.reduce((sum, gap) => sum + parseFloat(gap.style.height), 0) + mounted().length * 20
    expect(total).toBe(1000 * 20)
  })

  it('places the rows by their measured heights', () => {
    rowHeight = (key) => (key < name(10) ? 50 : 20)
    renderTree(<FileTree expandAll files={many(1000)} />)
    expect(listOffsetOf(name(12))).toBe(10 * 50 + 2 * 20)
  })

  it('keeps the row at the top of the view when the data changes in the background', () => {
    const filters = { search: '' }
    const { rerender } = renderTree(<FileTree expandAll files={many(1000)} resetKey={filters} />)
    scrollTo(HEADER + 500 * 20)

    // Un seed finito: stessi file, altro stato. Niente si sposta.
    rerender(<FileTree expandAll files={many(1000, { state: 'seeding' })} resetKey={filters} />)
    expect(scrollTop).toBe(HEADER + 500 * 20)
    // Dieci file sopra esclusi (fuori dalla lista): la vista sale con lei,
    // la stessa riga resta in cima.
    rerender(<FileTree expandAll files={many(1000).slice(10)} resetKey={filters} />)
    expect(scrollTop).toBe(HEADER + 490 * 20)
    expect(listOffsetOf(name(500))).toBe(scrollTop - HEADER)
    // Una ricerca nuova è un'altra lista: la vista non la insegue.
    rerender(<FileTree expandAll files={many(1000).slice(20)} resetKey={{ search: 'f' }} />)
    expect(scrollTop).toBe(HEADER + 490 * 20)
  })

  it('keeps the view on its row when rows above it are measured taller than estimated', () => {
    renderTree(<FileTree expandAll files={many(1000)} />)
    rowHeight = (key) => (key >= name(400) ? 40 : 20)
    scrollTo(HEADER + 500 * 20)
    // Le righe attorno alla 500 sono più alte della stima: la riga in cima resta quella.
    expect(listOffsetOf(name(500))).toBe(scrollTop - HEADER)
  })
})

describe('FileTree window keeps rows mounted', () => {
  it('keeps the focused row mounted out of the window', () => {
    renderTree(<FileTree expandAll actions={actions} files={many(1000)} />)
    const button = rowOf(name(5))!.querySelector('button')!
    act(() => button.focus())
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(5))).not.toBeNull()
    expect(document.activeElement).toBe(button)
    expect(rowOf(name(6))).toBeNull()
    expect(listOffsetOf(name(5))).toBe(5 * 20)
  })

  it('keeps the row of an open "⋯" menu mounted', async () => {
    renderTree(<FileTree expandAll actions={actions} files={many(1000)} />)
    const trigger = rowOf(name(5))!.querySelector<HTMLElement>('button[aria-label="More actions"]')!
    fireEvent.click(trigger)
    await screen.findByText('Exclude file')
    // Non per il fuoco: il menu l'ha preso, la riga resta per il trigger aperto.
    expect(rowOf(name(5))!.contains(document.activeElement)).toBe(false)
    expect(trigger.hasAttribute('data-popup-open')).toBe(true)
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(5))).not.toBeNull()
  })

  it('keeps the row of an open popover mounted', async () => {
    renderTree(<FileTree expandAll files={many(1000, { linked_paths: ['torrents/x.mkv'] })} />)
    fireEvent.click(rowOf(name(8))!.querySelector('button[aria-label="Hardlink"]')!)
    await screen.findByText('torrents/x.mkv')
    act(() => (document.activeElement as HTMLElement | null)?.blur())
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(8))).not.toBeNull()
    expect(rowOf(name(9))).toBeNull()
  })

  it('keeps the row of the context menu mounted while it is open', async () => {
    renderTree(<FileTree expandAll actions={actions} files={many(1000)} />)
    fireEvent.contextMenu(screen.getByText(name(7)))
    await screen.findByText('Exclude file')
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(7))).not.toBeNull()
  })
})

describe('FileTree window keyboard', () => {
  it('moves with Tab, Shift+Tab and the arrows to rows that are not mounted', () => {
    renderTree(<FileTree expandAll actions={actions} files={many(1000)} />)
    const first = rowOf(name(5))!.querySelector('button')!
    act(() => first.focus())
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(6))).toBeNull()

    // Dall'ultimo controllo della riga, il Tab va alla riga dopo, anche smontata.
    expect(fireEvent.keyDown(first, { key: 'Tab' })).toBe(false)
    expect(document.activeElement?.closest('tr')?.getAttribute('data-row-key')).toBe(name(6))
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' })
    expect(document.activeElement?.closest('tr')?.getAttribute('data-row-key')).toBe(name(7))
    fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true })
    expect(document.activeElement?.closest('tr')?.getAttribute('data-row-key')).toBe(name(6))
    fireEvent.keyDown(document.activeElement!, { key: 'ArrowUp' })
    expect(document.activeElement?.closest('tr')?.getAttribute('data-row-key')).toBe(name(5))
    // Le righe col fuoco restano montate, le altre lasciate tornano spazio.
    scrollTo(HEADER + 600 * 20)
    expect(rowOf(name(5))).not.toBeNull()
    expect(rowOf(name(7))).toBeNull()
  })

  it("leaves Tab to the browser inside a row and past the tree's last row", () => {
    renderTree(<FileTree actions={actions} files={[file('Movies/A.mkv'), file('Movies/B.mkv')]} />)
    // La cartella ha due controlli: il nome e "⋯".
    const folderName = screen.getByRole('button', { name: /Movies/ })
    expect(fireEvent.keyDown(folderName, { key: 'Tab' })).toBe(true)
    const last = rowOf('Movies/B.mkv')!.querySelector('button')!
    expect(fireEvent.keyDown(last, { key: 'Tab' })).toBe(true)
  })

  it('selects a SHIFT range for a pack across rows that are not mounted', () => {
    function Picker() {
      const selection = usePackSelection()
      return (
        <>
          <button type="button" onClick={() => selection.setActive(true)}>pick</button>
          <span data-testid="picked">{selection.files.length}</span>
          <FileTree expandAll files={many(1000)} selection={selection} />
        </>
      )
    }
    renderTree(<Picker />)
    fireEvent.click(screen.getByText('pick'))
    fireEvent.click(screen.getByRole('checkbox', { name: name(0) }))
    scrollTo(HEADER + 500 * 20)
    expect(rowOf(name(250))).toBeNull()
    fireEvent.click(screen.getByRole('checkbox', { name: name(500) }), { shiftKey: true })
    expect(screen.getByTestId('picked').textContent).toBe('501')
  })
})
