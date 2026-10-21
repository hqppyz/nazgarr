import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiKeysSection } from '@/pages/config/ApiKeysSection'

const create = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }))
const revoke = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }))
let keys: unknown[] = []
vi.mock('@/api/hooks/apiKeys', () => ({
  useApiKeys: () => ({ data: keys }),
  useCreateApiKey: () => create,
  useRevokeApiKey: () => revoke,
}))
vi.mock('@/lib/clipboard', () => ({ copyText: vi.fn(async () => true) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const key = (id: number, name: string, extra = {}) => ({
  id, name, prefix: `nzg_${id}abc`, level: 'read', created_at: '2026-10-01T10:00:00Z', last_used_at: null,
  revoked_at: null, ...extra,
})

// Le API key per servizi e script: il segreto si vede una volta sola, appena
// creata, e una chiave revocata non si revoca di nuovo.
describe('ApiKeysSection', () => {
  beforeEach(() => {
    create.mutate.mockReset()
    revoke.mutate.mockReset()
    keys = []
  })

  it('says when there is no key', () => {
    render(<ApiKeysSection />)
    expect(screen.getByText('No API key yet.')).toBeTruthy()
  })

  it('lists the keys by prefix only, with their access and status', () => {
    keys = [key(1, 'grafana'), key(2, 'old-script', { level: 'write', revoked_at: '2026-10-02T10:00:00Z' })]
    render(<ApiKeysSection />)
    // Telefono e tabella sono entrambi nel DOM (li separa il CSS).
    expect(screen.getAllByText('grafana')).toHaveLength(2)
    expect(screen.getAllByText('nzg_1abc…')).toHaveLength(2)
    expect(screen.getAllByText('Read and write')).toHaveLength(2)
    expect(screen.getAllByText(/^revoked /)).toHaveLength(2)
    // Revoca solo per quella attiva.
    expect(screen.getAllByRole('button', { name: 'Revoke' })).toHaveLength(2)
  })

  it('creates a key with the chosen access and shows its secret once', () => {
    create.mutate.mockImplementation((_body: unknown, options: { onSuccess: (k: { key: string }) => void }) =>
      options.onSuccess({ key: 'nzg_FULLSECRET' }))
    render(<ApiKeysSection />)
    fireEvent.click(screen.getByRole('button', { name: 'Add key' }))
    const dialog = screen.getByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Create key' }) as HTMLButtonElement
    expect(submit.disabled).toBe(true) // senza nome
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'grafana' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Read and write' }))
    fireEvent.click(submit)

    expect(create.mutate).toHaveBeenCalledWith({ name: 'grafana', level: 'write' }, expect.anything())
    expect(screen.getByText('Your new API key')).toBeTruthy()
    expect(screen.getByText('nzg_FULLSECRET')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('nzg_FULLSECRET')).toBeNull()
  })

  it('revokes the key of the row after its confirmation', () => {
    keys = [key(1, 'grafana'), key(2, 'backup')]
    render(<ApiKeysSection />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Revoke' })[1]) // la seconda della lista da telefono
    expect(revoke.mutate).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Revoke backup?')).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Revoke' }))
    expect(revoke.mutate).toHaveBeenCalledWith(2, expect.anything())
  })
})
