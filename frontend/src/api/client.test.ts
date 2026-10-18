import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, shouldRetryQuery, unwrap } from '@/api/client'
import { getToken, setToken } from '@/lib/authToken'

const BASE = 'http://nazgarr.test'

// Il fetch della singola chiamata (openapi-fetch lo accetta per richiesta):
// registra la Request che arriva davvero alla rete, dopo i middleware.
function serve(status: number, body: unknown) {
  const seen: Request[] = []
  const fetch = vi.fn(async (request: Request) => {
    seen.push(request)
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
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
})

describe('unwrap', () => {
  it('throws an ApiError with the status and the code of the error', async () => {
    const { fetch } = serve(404, { detail: { code: 'upload_not_found' } })
    const error = await unwrap(api.GET('/api/disks', { baseUrl: BASE, fetch })).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).code).toBe('upload_not_found')
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
  })
})
