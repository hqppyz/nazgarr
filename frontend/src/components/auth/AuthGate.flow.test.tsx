import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Il login per intero, col client vero (src/api/client.ts) e gli hook veri:
// solo la rete è finta. openapi-fetch prende fetch e Request quando il client
// nasce, quindi si sostituiscono prima degli import; la Request di Node non
// accetta URL relativi, quella della pagina sì.
const network = vi.hoisted(() => {
  const NodeRequest = globalThis.Request
  class PageRequest extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === 'string' ? new URL(input, 'http://nazgarr.test') : input, init)
    }
  }
  globalThis.Request = PageRequest as typeof Request
  const seen: Request[] = []
  let handler: (request: Request) => Promise<Response> = async () => new Response(null, { status: 404 })
  globalThis.fetch = (async (input: Request) => {
    seen.push(input)
    return handler(input)
  }) as typeof fetch
  return {
    seen,
    serve: (next: (request: Request) => Promise<Response>) => {
      handler = next
    },
  }
})

const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import { api, unwrap } from '@/api/client'
import { AuthGate } from '@/components/auth/AuthGate'
import { getToken, setToken } from '@/lib/authToken'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const coded = (status: number, code: string) => json({ detail: { code, params: {} } }, status)

const route = (request: Request) => `${request.method} ${new URL(request.url).pathname}`
const calls = () => network.seen.map(route)

function gate(children = <p>the app</p>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthGate>{children}</AuthGate>
    </QueryClientProvider>,
  )
}

function typeInto(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

beforeEach(() => {
  localStorage.clear()
  network.seen.length = 0
  toast.error.mockReset()
})

describe('AuthGate with the real client', () => {
  it('sends an ended session back to the login, and the login opens the app with the new token', async () => {
    setToken('old')
    network.serve(async (request) => {
      switch (route(request)) {
        case 'GET /api/auth/status':
          return json({ configured: true })
        case 'GET /api/auth/me':
          return request.headers.get('Authorization') === 'Bearer new'
            ? json({ username: 'admin' })
            : coded(401, 'auth_required')
        case 'POST /api/auth/login': {
          const body = await request.json()
          return body.password === 'secret123'
            ? json({ access_token: 'new', username: 'admin' })
            : coded(401, 'auth_invalid_credentials')
        }
      }
      return json(null, 404)
    })
    gate()

    await screen.findByRole('button', { name: 'Sign in' })
    // Il 401 di una sessione finita scarta il token vecchio.
    expect(getToken()).toBeNull()
    expect(screen.queryByText('the app')).toBeNull()

    // Una password sbagliata resta fuori, senza token.
    typeInto('Username', 'admin')
    typeInto('Password', 'typo')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Invalid credentials.'))
    expect(getToken()).toBeNull()
    expect(screen.queryByText('the app')).toBeNull()

    typeInto('Password', 'secret123')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByText('the app')
    expect(getToken()).toBe('new')
    const me = network.seen.filter((r) => route(r) === 'GET /api/auth/me').at(-1)
    expect(me?.headers.get('Authorization')).toBe('Bearer new')
  })

  it('does not log out of this instance when another one refuses its API key', async () => {
    setToken('tok')
    localStorage.setItem('nazgarr-instance', '3')
    network.serve(async (request) => {
      switch (route(request)) {
        case 'GET /api/auth/status':
          return json({ configured: true })
        case 'GET /api/auth/me':
          return json({ username: 'admin' })
        case 'GET /api/remote/3/api/disks':
          return coded(401, 'api_key_invalid')
      }
      return json(null, 404)
    })
    function Disks() {
      const { error } = useQuery({ queryKey: ['disks'], queryFn: () => unwrap(api.GET('/api/disks')) })
      return <p>{error ? error.message : 'the app'}</p>
    }
    gate(<Disks />)

    await screen.findByText('The API key is wrong or has been revoked')
    expect(getToken()).toBe('tok')
    expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull()
    // Il login e la sessione restano di questa istanza, col suo token.
    expect(calls()).toEqual(['GET /api/auth/status', 'GET /api/auth/me', 'GET /api/remote/3/api/disks'])
    for (const request of network.seen) expect(request.headers.get('Authorization')).toBe('Bearer tok')
  })

  it('creates the account only with the setup code, and says why it failed', async () => {
    let configured = false
    network.serve(async (request) => {
      switch (route(request)) {
        case 'GET /api/auth/status':
          return json({ configured })
        case 'GET /api/auth/me':
          return request.headers.get('Authorization') === 'Bearer first' ? json({ username: 'admin' }) : coded(401, 'auth_required')
        case 'POST /api/auth/setup': {
          const body = await request.json()
          if (body.setup_code !== 'ABCD-1234') return coded(403, 'auth_setup_code_invalid')
          configured = true
          return json({ access_token: 'first', username: body.username })
        }
      }
      return json(null, 404)
    })
    gate()

    const create = await screen.findByRole('button', { name: 'Create account' })
    typeInto('Username', 'admin')
    typeInto('Password', 'longenough')
    // Senza il codice stampato nel log del container non si crea niente.
    expect((create as HTMLButtonElement).disabled).toBe(true)
    typeInto('Setup code', 'WRONG')
    typeInto('Password', 'short')
    expect((create as HTMLButtonElement).disabled).toBe(true)
    typeInto('Password', 'longenough')
    expect((create as HTMLButtonElement).disabled).toBe(false)

    fireEvent.click(create)
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(toast.error.mock.calls[0][0]).toMatch(/^Account creation failed: Wrong setup code/)
    expect(getToken()).toBeNull()

    typeInto('Setup code', 'ABCD-1234')
    fireEvent.click(create)
    await screen.findByText('the app')
    expect(getToken()).toBe('first')
  })
})
