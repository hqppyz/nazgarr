import { UploadIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useSeedFiles } from '@/api/hooks/library'
import { FileBrowser } from '@/components/FileBrowser'
import { filesUnder, type TreeFileEntry } from '@/components/FileTree'
import { Button } from '@/components/ui/button'
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
// su uno privato. Sul file, o sulla cartella del torrent se ne contiene.
function UploadButton({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <Button size="xs" variant="outline" title={t('itemDetail.uploadOrReseedHelp')} onClick={() => navigate(to)}>
      <UploadIcon className="size-3.5" />
      {t('itemDetail.uploadOrReseed')}
    </Button>
  )
}

export function TorrentFolderView() {
  const { data, isPending } = useSeedFiles()

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <FileBrowser
      files={data ?? []}
      statusOptions={STATUS_OPTIONS}
      actions={{
        file: (file) =>
          isOrphan(file) && file.disk_id != null ? (
            <UploadButton to={newUploadLink({ diskId: file.disk_id, path: file.relative_path, isDir: false })} />
          ) : null,
        folder: (node) => {
          const files = filesUnder(node)
          const disks = new Set(files.map((f) => f.disk_id))
          if (!files.some(isOrphan) || disks.size !== 1 || files[0].disk_id == null) return null
          return <UploadButton to={newUploadLink({ diskId: files[0].disk_id, path: node.path, isDir: true })} />
        },
      }}
    />
  )
}
