import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchInstanceSnapshot } from '@/api/hooks/instances'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchInstanceSnapshot', () => {
  it('asks only for the uploads still in progress, here and through a remote instance', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const body = url.endsWith('/api/health') ? { version: '1.0.0' } : url.includes('/api/uploads') ? [] : {}
      return new Response(JSON.stringify(body), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await fetchInstanceSnapshot(null)
    await fetchInstanceSnapshot(3)

    const urls = fetchMock.mock.calls.map(([url]) => url)
    expect(urls).toContain('/api/uploads?scope=active')
    expect(urls).toContain('/api/remote/3/api/uploads?scope=active')
    expect(urls).not.toContain('/api/uploads')
  })
})
