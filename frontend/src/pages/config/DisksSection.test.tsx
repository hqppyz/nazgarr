import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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

vi.mock('@/api/hooks/disks', () => ({
  useDisks: () => ({ data: [disk], isPending: false }),
  useAvailableMounts: () => ({ data: { scan_root: '/data', mounts: [] } }),
  useCreateDisk: () => mutation,
  useUpdateDisk: () => mutation,
  useDeleteDisk: () => mutation,
  useVerifyDisk: () => ({ ...mutation, data: undefined }),
  useAddDiskFolder: () => mutation,
  useRemoveDiskFolder: () => ({ mutate: remove, isPending: false }),
  useBrowseDisk: () => ({ data: undefined, isPending: false }),
  useMkdir: () => mutation,
}))

afterEach(cleanup)

describe('DisksSection', () => {
  it('shows every media and seeding folder of a disk, each removable', () => {
    render(<DisksSection />)

    expect(screen.getByText('main')).toBeTruthy()
    for (const folder of ['torrents', 'movies', 'tv']) expect(screen.getByText(folder)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /Add/ }).length).toBeGreaterThanOrEqual(2)

    fireEvent.click(screen.getAllByRole('button', { name: 'Remove the folder (nothing changes on disk)' })[2])
    expect(remove).toHaveBeenCalledWith({ diskId: 1, folderId: 12 }, expect.anything())
  })
})
