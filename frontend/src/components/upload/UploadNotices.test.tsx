import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { UploadNotices } from '@/components/upload/UploadNotices'

const toast = vi.fn()
vi.mock('sonner', () => ({ toast: (...args: unknown[]) => toast(...args) }))
const get = vi.fn()
vi.mock('@/api/client', () => ({ api: { GET: (...args: unknown[]) => get(...args) }, unwrap: (p: Promise<unknown>) => p }))

afterEach(() => {
  cleanup()
  toast.mockReset()
  get.mockReset()
  localStorage.clear()
})

const renderIt = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <UploadNotices />
      </MemoryRouter>
    </QueryClientProvider>,
  )

describe('UploadNotices', () => {
  it('starts from now, without a backlog', async () => {
    get.mockResolvedValue({ notices: [], latest_id: 41 })
    renderIt()

    await waitFor(() => expect(localStorage.getItem('nazgarr-upload-notice')).toBe('41'))
    expect(get.mock.calls[0][1]).toEqual({ params: { query: {} } })
    expect(toast).not.toHaveBeenCalled()
  })

  it('shows each watched release once, with a button to open it', async () => {
    localStorage.setItem('nazgarr-upload-notice', '41')
    get.mockResolvedValue({
      notices: [{ id: 42, upload_id: 7, kind: 'ready', title: 'My Movie', year: 2024, path: 'releases/My.Movie.mkv' }],
      latest_id: 42,
    })
    renderIt()

    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1))
    expect(get.mock.calls[0][1]).toEqual({ params: { query: { after: 41 } } })
    const [title, options] = toast.mock.calls[0]
    expect(title).toBe('Upload ready for your decision')
    expect(options.description).toBe('My Movie (2024)')
    expect(options.action.label).toBe('Open')
    expect(localStorage.getItem('nazgarr-upload-notice')).toBe('42')
  })
})
