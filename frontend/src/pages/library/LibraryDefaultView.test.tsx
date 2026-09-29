import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { LibraryDefaultView } from '@/pages/library/LibraryDefaultView'

const setting = vi.hoisted(() => ({ value: null as string | null }))
vi.mock('@/api/hooks/settings', () => ({
  useSetting: () => ({ data: { key: 'library_default_view', value: setting.value }, isPending: false }),
}))

function renderAt() {
  render(
    <MemoryRouter initialEntries={['/library']}>
      <Routes>
        <Route path="/library" element={<LibraryDefaultView />} />
        <Route path="/library/folder" element={<p>folder view</p>} />
        <Route path="/library/poster" element={<p>poster view</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LibraryDefaultView', () => {
  it('opens Folder when no default was ever chosen', () => {
    setting.value = null
    renderAt()
    expect(screen.getByText('folder view')).toBeTruthy()
  })

  it('opens the view chosen in the settings', () => {
    setting.value = 'poster'
    renderAt()
    expect(screen.getByText('poster view')).toBeTruthy()
  })
})
