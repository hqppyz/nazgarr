import { QueryClient, QueryObserver, type Query } from '@tanstack/react-query'
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  applyPersistedDefaults,
  CACHE_MAX_AGE_MS,
  CACHE_REFRESH_MS,
  IDLE_VARIANT_GC_MS,
  LIBRARY_STALE_MS,
  shouldPersistQuery,
  skipUnchanged,
} from '@/lib/queryPersistence'

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

function client(queries: { queryHash: string; data: unknown }[], timestamp = Date.now()): PersistedClient {
  return {
    timestamp,
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

  it('rewrites an unchanged cache once a day, so it does not expire while in use', async () => {
    const start = 1_000_000_000
    let clock = start
    const restored = client([{ queryHash: 'media', data: [{ id: 1 }] }], start)
    const inner = fake(restored)
    const persister = skipUnchanged(inner, () => clock)
    await persister.restoreClient()
    const same = () => client([{ queryHash: 'media', data: restored.clientState.queries[0].state.data }], clock)
    clock = start + 60 * 60_000
    await persister.persistClient(same())
    expect(inner.persistClient).not.toHaveBeenCalled()
    clock = start + CACHE_REFRESH_MS + 1
    await persister.persistClient(same())
    expect(inner.persistClient).toHaveBeenCalledTimes(1)
    // Appena riscritta: di nuovo niente fino al giorno dopo.
    clock += 60_000
    await persister.persistClient(same())
    expect(inner.persistClient).toHaveBeenCalledTimes(1)
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

describe('applyPersistedDefaults', () => {
  it('keeps the persisted lists for the cache lifetime, and the detail sheets for the usual five minutes', () => {
    const queryClient = new QueryClient()
    applyPersistedDefaults(queryClient)
    const media = queryClient.getQueryDefaults(['library', 'media-files', undefined, 'all'])
    expect(media.gcTime).toBe(CACHE_MAX_AGE_MS)
    expect(media.staleTime).toBe(LIBRARY_STALE_MS)
    expect(queryClient.getQueryDefaults(['library', 'detail', 'movie', 603]).gcTime).toBeUndefined()
    expect(queryClient.getQueryDefaults(['settings', 'tracker_filter']).gcTime).toBe(CACHE_MAX_AGE_MS)
  })
})

describe('idle tracker variants', () => {
  afterEach(() => vi.useRealTimers())

  const filter = (queryClient: QueryClient, value: string) =>
    queryClient.setQueryData(['settings', 'tracker_filter'], { key: 'tracker_filter', value })

  // Una vista che guarda la variante e poi la lascia (cambio di filtro o di pagina).
  function watchThenLeave(queryClient: QueryClient, tracker: string) {
    const queryKey = ['library', 'media-files', undefined, tracker]
    queryClient.setQueryData(queryKey, [{ id: tracker }])
    const observer = new QueryObserver(queryClient, { queryKey, queryFn: () => [{ id: tracker }], staleTime: Infinity })
    const stop = observer.subscribe(() => undefined)
    return { queryKey, leave: stop }
  }

  it('drops a variant of a filter no longer chosen after the usual five minutes', () => {
    vi.useFakeTimers()
    const queryClient = new QueryClient()
    applyPersistedDefaults(queryClient)
    filter(queryClient, '3')
    const old = watchThenLeave(queryClient, 'all')
    const active = watchThenLeave(queryClient, '3')
    old.leave()
    active.leave()
    vi.advanceTimersByTime(IDLE_VARIANT_GC_MS - 1000)
    expect(queryClient.getQueryData(old.queryKey)).toBeDefined()
    vi.advanceTimersByTime(2000)
    expect(queryClient.getQueryData(old.queryKey)).toBeUndefined()
    // Quella del filtro scelto è la cache persistita: resta.
    expect(queryClient.getQueryData(active.queryKey)).toBeDefined()
  })

  it('drops the variant left behind when the filter changes with the view closed', () => {
    vi.useFakeTimers()
    const queryClient = new QueryClient()
    applyPersistedDefaults(queryClient)
    filter(queryClient, '3')
    const view = watchThenLeave(queryClient, '3')
    view.leave()
    vi.advanceTimersByTime(IDLE_VARIANT_GC_MS + 1000)
    expect(queryClient.getQueryData(view.queryKey)).toBeDefined()
    filter(queryClient, '5')
    vi.advanceTimersByTime(IDLE_VARIANT_GC_MS + 1000)
    expect(queryClient.getQueryData(view.queryKey)).toBeUndefined()
  })

  it('keeps a variant someone is still looking at', () => {
    vi.useFakeTimers()
    const queryClient = new QueryClient()
    applyPersistedDefaults(queryClient)
    filter(queryClient, '3')
    const view = watchThenLeave(queryClient, 'all')
    filter(queryClient, '5')
    vi.advanceTimersByTime(IDLE_VARIANT_GC_MS + 1000)
    expect(queryClient.getQueryData(view.queryKey)).toBeDefined()
    view.leave()
  })
})
