import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, shouldRetryQuery, unwrap } from '@/api/client'
import { getToken, setToken } from '@/lib/authToken'

const BASE = 'http://nazgarr.test'

// Il fetch della singola chiamata (openapi-fetch lo accetta per richiesta):
// registra la Request che arriva davvero alla rete, dopo i middleware.
function serve(status: number, body: unknown, contentType = 'application/json') {
  const seen: Request[] = []
  const fetch = vi.fn(async (request: Request) => {
    seen.push(request)
    const text = typeof body === 'string' ? body : JSON.stringify(body)
    return new Response(text, { status, headers: { 'Content-Type': contentType } })
  })
  return { fetch, seen }
}

describe('api client middleware', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('sends the token and keeps local calls local', async () => {
    setToken('tok')
    const { fetch, seen } = serve(200, [])
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(seen[0].headers.get('Authorization')).toBe('Bearer tok')
    expect(new URL(seen[0].url).pathname).toBe('/api/disks')
  })

  it('sends the calls of another instance through its proxy', async () => {
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch, seen } = serve(200, [])
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(new URL(seen[0].url).pathname).toBe('/api/remote/3/api/disks')
  })

  it('drops the token when this instance says the session is over', async () => {
    setToken('tok')
    const { fetch } = serve(401, { detail: { code: 'auth_required' } })
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(getToken()).toBeNull()
  })

  it('keeps the token when this instance refuses only the current password', async () => {
    setToken('tok')
    const { fetch } = serve(401, { detail: { code: 'auth_wrong_current_password' } })
    const { response } = await api.POST('/api/auth/change-password', {
      baseUrl: BASE,
      fetch,
      body: { current_password: 'typo', new_password: 'longenough' },
    })
    expect(response.status).toBe(401)
    expect(getToken()).toBe('tok')
  })

  it('keeps the token when another instance refuses its API key', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch } = serve(401, { detail: { code: 'api_key_invalid' } })
    const { response } = await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(response.status).toBe(401)
    expect(getToken()).toBe('tok')
  })

  it('still drops the token when the proxy itself finds the session over', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch } = serve(401, { detail: { code: 'auth_required' } })
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(getToken()).toBeNull()
  })

  it('sends no Authorization header without a token', async () => {
    const { fetch, seen } = serve(200, [])
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(seen[0].headers.has('Authorization')).toBe(false)
  })

  it('drops the token when no account exists any more', async () => {
    setToken('tok')
    const { fetch } = serve(401, { detail: { code: 'auth_setup_required' } })
    await api.GET('/api/disks', { baseUrl: BASE, fetch })
    expect(getToken()).toBeNull()
  })

  it('keeps the token on a 401 without a session code (a reverse proxy page, a plain detail)', async () => {
    setToken('tok')
    await api.GET('/api/disks', { baseUrl: BASE, fetch: serve(401, '<html>401</html>', 'text/html').fetch })
    expect(getToken()).toBe('tok')
    await api.GET('/api/disks', { baseUrl: BASE, fetch: serve(401, { detail: 'Not authenticated' }).fetch })
    expect(getToken()).toBe('tok')
  })

  it('keeps login and the instance registry on this instance while another one is shown', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch, seen } = serve(200, {})
    await api.POST('/api/auth/login', { baseUrl: BASE, fetch, body: { username: 'admin', password: 'secret123' } })
    await api.GET('/api/instances', { baseUrl: BASE, fetch })
    // Le credenziali di questa istanza non passano mai dal proxy verso un'altra.
    expect(seen.map((r) => new URL(r.url).pathname)).toEqual(['/api/auth/login', '/api/instances'])
  })

  it('forwards method, query, body and token unchanged through the proxy', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch, seen } = serve(200, {})
    await api.POST('/api/library/exclude', { baseUrl: BASE, fetch, body: { relative_path: 'a.mkv', is_dir: false } })
    await api.GET('/api/library/items', { baseUrl: BASE, fetch, params: { query: { tracker: 'itt' } } })

    const [post, get] = seen
    expect(post.method).toBe('POST')
    expect(new URL(post.url).pathname).toBe('/api/remote/3/api/library/exclude')
    expect(await post.json()).toEqual({ relative_path: 'a.mkv', is_dir: false })
    expect(post.headers.get('Authorization')).toBe('Bearer tok')
    expect(post.headers.get('Content-Type')).toBe('application/json')
    expect(new URL(get.url).pathname).toBe('/api/remote/3/api/library/items')
    expect(new URL(get.url).searchParams.get('tracker')).toBe('itt')
    expect(get.headers.get('Authorization')).toBe('Bearer tok')
  })

  it('keeps the abort signal of a proxied call', async () => {
    localStorage.setItem('nazgarr-instance', '3')
    const controller = new AbortController()
    const { fetch, seen } = serve(200, [])
    await api.GET('/api/disks', { baseUrl: BASE, fetch, signal: controller.signal })
    controller.abort()
    expect(seen[0].signal.aborted).toBe(true)
  })
})

// Un'istanza remota di una 0.9.x rilasciata: le path che conosce, il resto
// come risponderebbe lei (lo storico finisce su /api/uploads/{upload_id}, 422).
function olderRemote(routes: Record<string, unknown>, missing = 404) {
  const seen: string[] = []
  const fetch = vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    seen.push(`${url.pathname}${url.search}`)
    const body = routes[url.pathname]
    return body === undefined
      ? new Response(JSON.stringify({ detail: 'Not Found' }), { status: missing, headers: { 'Content-Type': 'application/json' } })
      : new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  return { fetch, seen }
}

describe('older remote instances (audit 2026-10-18)', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  const job = (id: number, status: string) => ({ id, status })

  it('builds the upload history from the plain list when the remote has no /history', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch, seen } = olderRemote(
      { '/api/remote/3/api/uploads': [job(9, 'running'), job(7, 'done'), job(8, 'failed'), job(5, 'cancelled')] },
      422,
    )
    const data = await unwrap(api.GET('/api/uploads/history', { baseUrl: BASE, fetch, params: { query: { limit: 50 } } }))
    expect(data).toEqual({ jobs: [job(8, 'failed'), job(7, 'done'), job(5, 'cancelled')], total: 3, next_before_id: null })
    expect(seen).toEqual(['/api/remote/3/api/uploads/history?limit=50', '/api/remote/3/api/uploads'])
    expect(fetch.mock.calls[1][0].headers.get('Authorization')).toBe('Bearer tok')
  })

  it('builds the review queue from the plain list when the remote has no /queue', async () => {
    localStorage.setItem('nazgarr-instance', '3')
    const { fetch } = olderRemote({ '/api/remote/3/api/reviews': [{ id: 1 }, { id: 2 }] })
    const data = await unwrap(api.GET('/api/reviews/queue', { baseUrl: BASE, fetch, params: { query: { offset: 0, limit: 100 } } }))
    expect(data).toEqual({ items: [{ id: 1 }, { id: 2 }], total: 2, offset: 0, next_offset: null })
  })

  it('keeps the new endpoints when the remote has them, and the errors of this instance', async () => {
    localStorage.setItem('nazgarr-instance', '3')
    const page = { items: [], total: 0, offset: 0, next_offset: null }
    const current = olderRemote({ '/api/remote/3/api/reviews/queue': page, '/api/remote/3/api/reviews': [{ id: 1 }] })
    expect(await unwrap(api.GET('/api/reviews/queue', { baseUrl: BASE, fetch: current.fetch }))).toEqual(page)
    expect(current.seen).toEqual(['/api/remote/3/api/reviews/queue'])

    // Questa istanza ha sempre gli endpoint della sua interfaccia: un 404 resta un errore.
    localStorage.clear()
    const local = olderRemote({ '/api/reviews': [{ id: 1 }] })
    const error = await unwrap(api.GET('/api/reviews/queue', { baseUrl: BASE, fetch: local.fetch })).catch((e: unknown) => e)
    expect((error as ApiError).status).toBe(404)
    expect(local.seen).toEqual(['/api/reviews/queue'])
  })
})

describe('unwrap', () => {
  it('throws an ApiError with the status and the code of the error', async () => {
    const { fetch } = serve(404, { detail: { code: 'upload_not_found' } })
    const error = await unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch })).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).code).toBe('upload_not_found')
  })

  it('translates the code with its params', async () => {
    const { fetch } = serve(409, { detail: { code: 'upload_source_not_a_file', params: { path: '/data/x.mkv' } } })
    const error = await unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch })).catch((e: unknown) => e)
    expect((error as ApiError).message).toBe('Not a regular file (a symlink?): /data/x.mkv')
    expect((error as ApiError).status).toBe(409)
  })

  it('returns the data of a successful call', async () => {
    const { fetch } = serve(200, [{ id: 1 }])
    expect(await unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch }))).toEqual([{ id: 1 }])
  })

  it('keeps a plain detail as the message', async () => {
    const { fetch } = serve(422, { detail: 'bad value' })
    const error = await unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch })).catch((e: unknown) => e)
    expect((error as ApiError).message).toBe('bad value')
    expect((error as ApiError).code).toBeUndefined()
  })
})

describe('shouldRetryQuery', () => {
  it('never retries an answer of the server, only failures', () => {
    expect(shouldRetryQuery(0, new ApiError('gone', 404))).toBe(false)
    expect(shouldRetryQuery(0, new ApiError('read only', 403))).toBe(false)
    expect(shouldRetryQuery(0, new ApiError('boom', 500))).toBe(true)
    expect(shouldRetryQuery(0, new ApiError('slow down', 429))).toBe(true)
    expect(shouldRetryQuery(0, new TypeError('Failed to fetch'))).toBe(true)
    expect(shouldRetryQuery(3, new TypeError('Failed to fetch'))).toBe(false)
    expect(shouldRetryQuery(0, new ApiError('timeout', 408))).toBe(true)
    expect(shouldRetryQuery(0, new ApiError('login required', 401, 'auth_required'))).toBe(false)
  })

  // Come lo usa main.tsx: defaultOptions.queries.retry.
  async function attempts(status: number) {
    const { fetch } = serve(status, { detail: { code: 'upload_not_found' } })
    const client = new QueryClient({ defaultOptions: { queries: { retry: shouldRetryQuery, retryDelay: 0 } } })
    await client
      .fetchQuery({ queryKey: ['x', status], queryFn: () => unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch })) })
      .catch(() => undefined)
    return fetch.mock.calls.length
  }

  it('asks a 4xx once, and a 5xx up to four times', async () => {
    expect(await attempts(404)).toBe(1)
    expect(await attempts(403)).toBe(1)
    expect(await attempts(503)).toBe(4)
  })
})
