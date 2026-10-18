import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { ClientWarnings } from '@/pages/config/ClientWarnings'

function renderWith(warnings: string[], enabled = true) {
  const get = vi.spyOn(api, 'GET').mockResolvedValue({
    data: { status: 'ok', warnings, error: null }, error: undefined, response: new Response(),
  } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ClientWarnings clientId={3} enabled={enabled} />
    </QueryClientProvider>,
  )
  return get
}

describe('ClientWarnings', () => {
  afterEach(() => vi.restoreAllMocks())

  it('warns when Transmission renames incomplete files', async () => {
    const get = renderWith(['rename_partial_files'])
    expect(await screen.findByRole('note')).toHaveTextContent('.part')
    expect(get).toHaveBeenCalledWith('/api/torrent-clients/{torrent_client_id}/warnings', {
      params: { path: { torrent_client_id: 3 } },
    })
  })

  it('shows nothing without warnings, and asks nothing of a disabled client', async () => {
    renderWith([])
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.queryByRole('note')).toBeNull()
    vi.restoreAllMocks()
    expect(renderWith(['rename_partial_files'], false)).not.toHaveBeenCalled()
  })
})
