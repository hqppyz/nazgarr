import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { AuthGate } from '@/components/auth/AuthGate'

interface Result {
  data?: unknown
  isPending?: boolean
  isError?: boolean
  isFetching?: boolean
  error?: unknown
}

const state: { status: Result; me: Result } = { status: {}, me: {} }
const refetch = vi.fn()

vi.mock('@/api/hooks/auth', () => ({
  useAuthStatus: () => ({ isPending: false, isError: false, isFetching: false, refetch, ...state.status }),
  useMe: () => ({ isPending: false, isError: false, isFetching: false, refetch, ...state.me }),
  useLogin: () => ({ mutate: vi.fn(), isPending: false }),
  useSetup: () => ({ mutate: vi.fn(), isPending: false }),
  logout: vi.fn(),
}))

function gate() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthGate>
        <p>the app</p>
      </AuthGate>
    </QueryClientProvider>,
  )
}

describe('AuthGate', () => {
  beforeEach(() => {
    state.status = {}
    state.me = {}
    refetch.mockClear()
  })

  it('asks to retry instead of offering the account creation when the server does not answer', () => {
    state.status = { isError: true, error: new ApiError('Bad gateway', 502) }
    gate()
    expect(screen.queryByText('Create account')).toBeNull()
    screen.getByRole('button', { name: 'Retry' }).click()
    expect(refetch).toHaveBeenCalled()
  })

  it('offers the account creation only on an instance that is really not configured', () => {
    state.status = { data: { configured: false } }
    gate()
    expect(screen.getByText('Create account')).toBeTruthy()
  })

  it('asks to log in again only on a 401', () => {
    state.status = { data: { configured: true } }
    state.me = { isError: true, error: new ApiError('Login required', 401, 'auth_required') }
    gate()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
  })

  it('waits for the server, not for a new login, when the session check fails otherwise', () => {
    state.status = { data: { configured: true } }
    state.me = { isError: true, error: new TypeError('Failed to fetch') }
    gate()
    expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('keeps the app open when a later session check fails but the user is known', () => {
    state.status = { data: { configured: true } }
    state.me = { data: { username: 'admin' }, isError: true, error: new TypeError('Failed to fetch') }
    gate()
    expect(screen.getByText('the app')).toBeTruthy()
  })
})
