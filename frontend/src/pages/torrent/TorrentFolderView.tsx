import { useSeedFiles } from '@/api/hooks/library'
import { FileBrowser } from '@/components/FileBrowser'
import { useTreeMenu } from '@/components/useTreeMenu'
import { t } from '@/lib/i18n'
import type { StatusOption } from '@/lib/library-filters'

const STATUS_OPTIONS: StatusOption[] = [
  { value: 'all', label: t('library.stateAll') },
  { value: 'seeding', label: t('library.stateSeeding') },
  { value: 'ignored', label: t('library.stateIgnored') },
  { value: 'orphan_torrent', label: t('library.stateOrphanTorrent') },
]

// Un torrent orfano si può ripubblicare: capita di scaricarlo da un tracker
// pubblico e volerlo anche su uno privato. Dal menu contestuale del file, o
// della cartella del torrent se ne contiene (useTreeMenu).
export function TorrentFolderView() {
  const { data, isPending } = useSeedFiles()
  const menu = useTreeMenu('orphan_torrent')

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <>
      <FileBrowser
        files={data ?? []}
        statusOptions={STATUS_OPTIONS}
        header={<p className="text-xs text-muted-foreground">{t('library.torrentRightClickHint')}</p>}
        actions={menu.actions}
      />
      {menu.dialog}
    </>
  )
}
