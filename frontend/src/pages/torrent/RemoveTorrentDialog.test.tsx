import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Schemas } from '@/api/client'
import { RemoveTorrentDialog } from '@/pages/torrent/RemoveTorrentDialog'

type Torrent = Schemas['NotImportedItem']

const remove = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }))
vi.mock('@/api/hooks/library', () => ({ useRemoveNotImported: () => remove }))
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

const torrent = (extra: Partial<Torrent> = {}) =>
  ({
    client_torrent_id: 7, name: 'Old.Movie.1080p.mkv', client: 'qbit', total_bytes: 2e9,
    seed_requirement: { status: 'met', remaining: {} }, removal_warnings: [], ...extra,
  }) as unknown as Torrent

// La conferma che toglie un torrent dal client e ne cancella i file: dice
// cosa succede e gli avvisi che restano, e chiede quel torrent, non un altro.
describe('RemoveTorrentDialog', () => {
  beforeEach(() => {
    remove.mutate.mockReset()
    remove.isPending = false
  })

  it('renders nothing without a torrent', () => {
    render(<RemoveTorrentDialog torrent={null} onClose={vi.fn()} />)
    expect(screen.queryByText('Remove the torrent and its files?')).toBeNull()
  })

  it('says what goes, lists the warnings, and removes that torrent on confirm', () => {
    const onClose = vi.fn()
    remove.mutate.mockImplementation((_id: number, options: { onSuccess: () => void }) => options.onSuccess())
    render(
      <RemoveTorrentDialog
        torrent={torrent({ removal_warnings: [{ code: 'last_seeder', params: {}, blocking: false }] })}
        onClose={onClose}
      />,
    )
    expect(screen.getByText('Remove the torrent and its files?')).toBeTruthy()
    expect(screen.getByText(/removed from qbit and its files deleted from the disk, freeing 2/)).toBeTruthy()
    expect(screen.getByText('Old.Movie.1080p.mkv')).toBeTruthy()
    expect(screen.getByText(/you are the last seeder/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Remove and delete the files' }))
    expect(remove.mutate).toHaveBeenCalledWith(7, expect.anything())
    expect(toast.success).toHaveBeenCalledWith('Old.Movie.1080p.mkv removed from the client, files deleted.')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('keeps the dialog open with the error when the server refuses', () => {
    const onClose = vi.fn()
    remove.mutate.mockImplementation((_id: number, options: { onError: (e: Error) => void }) =>
      options.onError(new Error('Removal blocked')))
    render(<RemoveTorrentDialog torrent={torrent()} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove and delete the files' }))
    expect(toast.error).toHaveBeenCalledWith('Removal blocked')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('cannot be confirmed or dismissed twice while the removal runs', () => {
    remove.isPending = true
    const onClose = vi.fn()
    render(<RemoveTorrentDialog torrent={torrent()} onClose={onClose} />)
    expect((screen.getByRole('button', { name: 'Remove and delete the files' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
