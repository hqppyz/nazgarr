import { MutationCache, QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { reportMutationError, TOAST_ERRORS } from '@/lib/mutationErrors'

const toastError = vi.hoisted(() => vi.fn())
vi.mock('sonner', () => ({ toast: { error: toastError } }))

function client() {
  return new QueryClient({
    mutationCache: new MutationCache({ onError: (error, _v, _c, mutation) => reportMutationError(error, mutation) }),
  })
}

const failing = () => Promise.reject(new Error('This API key is read only.'))

describe('reportMutationError', () => {
  beforeEach(() => toastError.mockClear())

  it('shows why an action failed when its callers do not', async () => {
    const queryClient = client()
    await queryClient.getMutationCache().build(queryClient, { mutationFn: failing, meta: TOAST_ERRORS }).execute(undefined).catch(() => undefined)
    expect(toastError).toHaveBeenCalledWith('Failed: This API key is read only.')
  })

  it('stays quiet for mutations that report their own errors', async () => {
    const queryClient = client()
    await queryClient.getMutationCache().build(queryClient, { mutationFn: failing }).execute(undefined).catch(() => undefined)
    expect(toastError).not.toHaveBeenCalled()
  })
})
