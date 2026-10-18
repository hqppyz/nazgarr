import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DisksSection } from '@/pages/config/DisksSection'

const remove = vi.fn()
const disk = {
  id: 1, label: 'main', root_path: '/data', st_dev: 1, new_torrent_rel_path: null, upload_rel_path: null,
  watch_rel_path: null, media_rel_path: 'movies', torrents_rel_path: 'torrents',
  media_folders: ['movies', 'tv'], seeding_folders: ['torrents'],
  folders: [
    { id: 10, kind: 'seeding', relative_path: 'torrents' },
    { id: 11, kind: 'media', relative_path: 'movies' },
    { id: 12, kind: 'media', relative_path: 'tv' },
  ],
}
const mutation = { mutate: vi.fn(), isPending: false }
const deleteDisk = vi.fn()
const preview = {
  current: {
    folders: 3, media_files: 1200, seed_files: 800, reviews: 4, executions: 2, match_attempts: 0, watch_entries: 0,
    client_links: 1, upload_jobs: 5, busy: null as string | null,
  },
}

vi.mock('@/api/hooks/disks', () => ({
  useDisks: () => ({ data: [disk], isPending: false }),
  useAvailableMounts: () => ({ data: { scan_root: '/data', scan_roots: ['/data'], scope_source: 'mounts', mounts: [], detected: [], warnings: [] } }),
  useCreateDisk: () => mutation,
  useUpdateDisk: () => mutation,
  useDeleteDisk: () => ({ mutate: deleteDisk, isPending: false }),
  useDiskDeletePreview: (_id: number, enabled: boolean) => ({
    data: enabled ? preview.current : undefined, isFetching: false, error: null,
  }),
  useVerifyDisk: () => ({ ...mutation, data: undefined }),
  useAddDiskFolder: () => mutation,
  useRemoveDiskFolder: () => ({ mutate: remove, isPending: false }),
  useBrowseDisk: () => ({ data: undefined, isPending: false }),
  useMkdir: () => mutation,
}))


describe('DisksSection', () => {
  it('shows every media and seeding folder of a disk, each removable', () => {
    render(<DisksSection />)

    expect(screen.getByText('main')).toBeTruthy()
    for (const folder of ['torrents', 'movies', 'tv']) expect(screen.getByText(folder)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Add/ }).length).toBeGreaterThanOrEqual(2)

    // Togliere una cartella ora chiede conferma.
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove the folder (nothing changes on disk)' })[2])
    expect(remove).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(remove).toHaveBeenCalledWith({ diskId: 1, folderId: 12 }, expect.anything())
  })
})

describe('deleting a disk', () => {
  it('says what goes with it, that no file is touched, and asks first', () => {
    render(<DisksSection />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByText('Library file records')).toBeTruthy()
    expect(screen.getByText((1200).toLocaleString('en-US'))).toBeTruthy()
    expect(screen.queryByText('Search records')).toBeNull() // zero: non si mostra
    expect(screen.getByText('5 uploads from this disk stay in the history, without the disk.')).toBeTruthy()
    expect(screen.getByText('No file on the disk is touched, and torrents stay in their clients.')).toBeTruthy()
    expect(deleteDisk).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' }).at(-1)!)
    expect(deleteDisk).toHaveBeenCalledWith(1)
  })

  it('does not offer the delete while a reseed works on its files', () => {
    preview.current = { ...preview.current, busy: 'reseed' }
    render(<DisksSection />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('alert').textContent).toContain('A reseed is working on the files of this disk')
    expect((screen.getAllByRole('button', { name: 'Delete' }).at(-1) as HTMLButtonElement).disabled).toBe(true)
  })
})
