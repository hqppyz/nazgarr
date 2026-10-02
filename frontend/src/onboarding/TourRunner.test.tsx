import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_STATE } from '@/onboarding/state'
import { TourRunner } from '@/onboarding/TourRunner'
import { tourStore } from '@/onboarding/tourStore'

interface Highlight {
  element?: Element
  popover: { title: string; showButtons: string[]; onNextClick: () => void; onCloseClick: () => void }
}
const highlights: Highlight[] = []
const destroy = vi.fn()
vi.mock('driver.js', () => ({
  driver: () => ({ highlight: (h: Highlight) => highlights.push(h), destroy, refresh: vi.fn() }),
}))
vi.mock('driver.js/dist/driver.css', () => ({}))
vi.mock('@/onboarding/state', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/onboarding/state')>()),
  useOnboarding: () => ({ isPending: false, state: DEFAULT_STATE, save: vi.fn(), saving: false }),
}))

const where = { path: '' }
function Location() {
  const location = useLocation()
  useEffect(() => {
    where.path = location.pathname + location.search
  }, [location])
  return null
}

function setup() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <TourRunner />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
const page = (html: string) => {
  document.getElementById('page')?.remove()
  const div = document.createElement('div')
  div.id = 'page'
  div.innerHTML = html
  document.body.appendChild(div)
}
const tick = () => act(() => vi.advanceTimersByTime(400))
const last = () => highlights[highlights.length - 1]

beforeEach(() => {
  vi.useFakeTimers()
  highlights.length = 0
  destroy.mockClear()
})
afterEach(() => {
  act(() => tourStore.stop())
  cleanup()
  document.getElementById('page')?.remove()
  vi.useRealTimers()
})

describe('TourRunner', () => {
  it('goes to the screen of the tour and highlights its first field', () => {
    setup()
    page('<div data-tour="storage.card"></div><button data-tour="storage.add"></button>')

    act(() => tourStore.start('storage'))
    tick()

    expect(where.path).toBe('/config?tab=storage')
    expect(last().element?.getAttribute('data-tour')).toBe('storage.card')
    expect(last().popover.title).toBe('Your disks')
  })

  it('waits for the user to do the thing, then moves on by itself', () => {
    setup()
    page('<div data-tour="storage.card"></div><button data-tour="storage.add"></button>')
    act(() => tourStore.start('storage'))
    tick()
    act(() => last().popover.onNextClick())
    tick()
    expect(last().element?.getAttribute('data-tour')).toBe('storage.add')
    expect(last().popover.showButtons).not.toContain('next') // si va avanti cliccando Add

    page('<button data-tour="storage.add"></button><div data-slot="dialog-content" data-tour="storage.dialog"><div data-tour="storage.dialog.label"></div></div>')
    tick()
    tick()

    expect(last().element?.getAttribute('data-tour')).toBe('storage.dialog.label')
  })

  it('skips what is already configured', () => {
    setup()
    page('<button data-tour="storage.add"></button><table><tr data-tour="storage.row"><td><button data-tour="storage.media-folder"></button></td></tr></table>')
    act(() => {
      tourStore.start('storage')
      tourStore.goTo(1)
    })
    tick()
    tick()

    expect(last().element?.getAttribute('data-tour')).toBe('storage.media-folder')
  })

  it('steps aside while another dialog or list is open, and comes back after', () => {
    setup()
    page('<table><tr data-tour="storage.row"><td><button data-tour="storage.media-folder"></button></td></tr></table>')
    act(() => {
      tourStore.start('storage')
      tourStore.goTo(5) // la cartella dei media
    })
    tick()
    const before = highlights.length
    page('<table><tr data-tour="storage.row"><td><button data-tour="storage.media-folder"></button></td></tr></table><div data-slot="dialog-content">folder browser</div>')
    destroy.mockClear()
    tick()
    expect(destroy).toHaveBeenCalled()

    page('<table><tr data-tour="storage.row"><td><button data-tour="storage.media-folder" data-tour-filled="true"></button></td></tr></table><button data-tour="storage.seeding-folder"></button>')
    tick()
    tick()
    expect(highlights.length).toBeGreaterThan(before)
    expect(last().element?.getAttribute('data-tour')).toBe('storage.seeding-folder') // cartella scelta: avanti
  })
})
