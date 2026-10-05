import { useSeedFiles } from '@/api/hooks/library'
import { FileBrowser } from '@/components/FileBrowser'
import { TorrentViewSwitch } from '@/components/LibraryViewSwitch'
import { useTreeMenu } from '@/components/useTreeMenu'
import { useRingLoader } from '@/components/RingLoader'
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
  const query = useSeedFiles()
  const { data } = query
  const loader = useRingLoader(query)
  const menu = useTreeMenu('orphan_torrent')

  if (loader) return loader

  return (
    <>
      <FileBrowser
        files={data ?? []}
        statusOptions={STATUS_OPTIONS}
        header={
          <>
            <TorrentViewSwitch />
            {/* Clic destro col mouse, pressione lunga o ⋯ su touch. */}
            <p className="text-xs text-muted-foreground pointer-coarse:hidden">{t('library.torrentRightClickHint')}</p>
            <p className="hidden text-xs text-muted-foreground pointer-coarse:block">{t('library.torrentTouchHint')}</p>
          </>
        }
        actions={menu.actions}
      />
      {menu.dialog}
    </>
  )
}
