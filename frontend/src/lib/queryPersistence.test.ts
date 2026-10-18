import type { Query } from '@tanstack/react-query'
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client'
import { describe, expect, it, vi } from 'vitest'

import { shouldPersistQuery, skipUnchanged } from '@/lib/queryPersistence'

const query = (key: unknown[], status: string) => ({ queryKey: key, state: { status } }) as unknown as Query

describe('shouldPersistQuery', () => {
  it('persists only successful library views, never runs, reviews or auth', () => {
    expect(shouldPersistQuery(query(['library', 'media-files', undefined, 'all'], 'success'))).toBe(true)
    expect(shouldPersistQuery(query(['library', 'not-imported'], 'success'))).toBe(true)
    expect(shouldPersistQuery(query(['library', 'items', undefined, 'all'], 'error'))).toBe(false)
    expect(shouldPersistQuery(query(['runs'], 'success'))).toBe(false)
    expect(shouldPersistQuery(query(['auth', 'me'], 'success'))).toBe(false)
  })

  it('skips the detail sheets and the tracker variants not in use', () => {
    expect(shouldPersistQuery(query(['library', 'detail', 'movie', 603], 'success'))).toBe(false)
    expect(shouldPersistQuery(query(['library', 'seed-files', undefined, '3'], 'success'), '3')).toBe(true)
    expect(shouldPersistQuery(query(['library', 'seed-files', undefined, 'all'], 'success'), '3')).toBe(false)
  })

  it('keeps the tracker filter, so the right variant draws at once', () => {
    expect(shouldPersistQuery(query(['settings', 'tracker_filter'], 'success'))).toBe(true)
    expect(shouldPersistQuery(query(['settings', 'size_units'], 'success'))).toBe(false)
  })
})

function client(queries: { queryHash: string; data: unknown }[]): PersistedClient {
  return {
    timestamp: Date.now(),
    buster: 'x',
    clientState: {
      mutations: [],
      queries: queries.map(({ queryHash, data }) => ({ queryHash, queryKey: [queryHash], state: { data } })),
    },
  } as unknown as PersistedClient
}

describe('skipUnchanged', () => {
  function fake(restored?: PersistedClient) {
    return {
      persistClient: vi.fn((_client: PersistedClient) => undefined),
      restoreClient: vi.fn(async () => restored),
      removeClient: vi.fn(() => undefined),
    } satisfies Persister
  }

  it('writes only when a persisted query got new data', async () => {
    const files = [{ id: 1 }]
    const inner = fake()
    const persister = skipUnchanged(inner)
    await persister.persistClient(client([{ queryHash: 'media', data: files }]))
    // Un poll di un'altra query: stesso oggetto (structural sharing), niente da scrivere.
    await persister.persistClient(client([{ queryHash: 'media', data: files }]))
    expect(inner.persistClient).toHaveBeenCalledTimes(1)
    await persister.persistClient(client([{ queryHash: 'media', data: [{ id: 1 }, { id: 2 }] }]))
    await persister.persistClient(client([{ queryHash: 'media', data: files }, { queryHash: 'seed', data: [] }]))
    expect(inner.persistClient).toHaveBeenCalledTimes(3)
  })

  it('does not rewrite the cache it just restored', async () => {
    const restored = client([{ queryHash: 'media', data: [{ id: 1 }] }])
    const inner = fake(restored)
    const persister = skipUnchanged(inner)
    await persister.restoreClient()
    await persister.persistClient(client([{ queryHash: 'media', data: restored.clientState.queries[0].state.data }]))
    expect(inner.persistClient).not.toHaveBeenCalled()
  })

  it('writes again after the cache was removed (logout)', async () => {
    const files = [{ id: 1 }]
    const inner = fake()
    const persister = skipUnchanged(inner)
    await persister.persistClient(client([{ queryHash: 'media', data: files }]))
    await persister.removeClient()
    await persister.persistClient(client([{ queryHash: 'media', data: files }]))
    expect(inner.persistClient).toHaveBeenCalledTimes(2)
  })
})
