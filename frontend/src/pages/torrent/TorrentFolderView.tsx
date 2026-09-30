import { UploadIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useSeedFiles } from '@/api/hooks/library'
import { FileBrowser } from '@/components/FileBrowser'
import { filesUnder, type TreeFileEntry } from '@/components/FileTree'
import type { RowMenuItem } from '@/components/RowContextMenu'
import { t } from '@/lib/i18n'
import type { StatusOption } from '@/lib/library-filters'
import { newUploadLink } from '@/lib/upload'

const STATUS_OPTIONS: StatusOption[] = [
  { value: 'all', label: t('library.stateAll') },
  { value: 'seeding', label: t('library.stateSeeding') },
  { value: 'ignored', label: t('library.stateIgnored') },
  { value: 'orphan_torrent', label: t('library.stateOrphanTorrent') },
]

const isOrphan = (file: TreeFileEntry) => file.state === 'orphan_torrent' && !file.excluded

// Un torrent orfano (in seed, ma senza il suo file in libreria) si può
// ripubblicare: capita di scaricarlo da un tracker pubblico e volerlo anche
// su uno privato. Dal menu contestuale del file, o della cartella del
// torrent se ne contiene.
function uploadItem(navigate: (to: string) => void, to: string): RowMenuItem {
  return { label: t('itemDetail.uploadOrReseed'), icon: <UploadIcon />, onSelect: () => navigate(to) }
}

export function TorrentFolderView() {
  const { data, isPending } = useSeedFiles()
  const navigate = useNavigate()

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <FileBrowser
      files={data ?? []}
      statusOptions={STATUS_OPTIONS}
      header={<p className="text-xs text-muted-foreground">{t('library.torrentRightClickHint')}</p>}
      actions={{
        file: (file) =>
          isOrphan(file) && file.disk_id != null
            ? [uploadItem(navigate, newUploadLink({ diskId: file.disk_id, path: file.relative_path, isDir: false }))]
            : [],
        folder: (node) => {
          const files = filesUnder(node)
          const disks = new Set(files.map((f) => f.disk_id))
          if (!files.some(isOrphan) || disks.size !== 1 || files[0].disk_id == null) return []
          return [uploadItem(navigate, newUploadLink({ diskId: files[0].disk_id, path: node.path, isDir: true }))]
        },
      }}
    />
  )
}
