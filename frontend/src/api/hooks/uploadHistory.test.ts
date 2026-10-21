import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  api: { GET: (...args: unknown[]) => get(...args) },
}))

import { fetchHistoryPage } from '@/api/hooks/uploads'

const job = (id: number, status: string) => ({ id, status, targets: [] })
const failed = (status: number) => ({ data: undefined, error: { detail: 'Not Found' }, response: new Response(null, { status }) })

describe('fetchHistoryPage', () => {
  beforeEach(() => get.mockReset())

  it('reads one page of the history', async () => {
    get.mockResolvedValue({ data: { jobs: [job(9, 'done')], total: 1, next_before_id: null }, error: undefined })

    expect(await fetchHistoryPage(null)).toEqual({ jobs: [job(9, 'done')], total: 1, next_before_id: null })
    expect(get).toHaveBeenCalledTimes(1)
  })

  it.each([404, 405, 422])('falls back to the full list on an older instance (%s)', async (status) => {
    // Audit 2026-10-18 (R10): un'istanza remota 0.9.x non ha lo storico a
    // pagine, e tutta la pagina degli upload diventava un errore.
    get.mockResolvedValueOnce(failed(status)).mockResolvedValueOnce({
      data: [job(3, 'done'), job(7, 'queued'), job(5, 'cancelled')], error: undefined,
    })

    expect(await fetchHistoryPage(null)).toEqual({ jobs: [job(5, 'cancelled'), job(3, 'done')], total: 2, next_before_id: null })
    expect(get.mock.calls[1][0]).toBe('/api/uploads')
  })

  it('keeps any other error', async () => {
    get.mockResolvedValue(failed(500))

    await expect(fetchHistoryPage(null)).rejects.toMatchObject({ status: 500 })
    expect(get).toHaveBeenCalledTimes(1)
  })
})
