import { useMemo } from 'react'

import { useLibraryDuplicates, useMediaFiles } from '@/api/hooks/library'
import { FileBrowser } from '@/components/FileBrowser'
import { LibraryViewSwitch } from '@/components/LibraryViewSwitch'
import { useTreeMenu } from '@/components/useTreeMenu'
import { t } from '@/lib/i18n'
import { DUPLICATES_STATUS, fileKey, type StatusOption } from '@/lib/library-filters'

const STATUS_OPTIONS: StatusOption[] = [
  { value: 'all', label: t('library.stateAll') },
  { value: 'seeding', label: t('library.stateSeeding') },
  { value: 'orphan_media', label: t('library.stateOrphanMedia') },
  { value: DUPLICATES_STATUS, label: t('library.stateDuplicates') },
]

export function FolderView() {
  const { data, isPending } = useMediaFiles()
  const { data: duplicates } = useLibraryDuplicates()
  const menu = useTreeMenu('orphan_media')

  const duplicateKeys = useMemo(
    () => (duplicates ? new Set(duplicates.flatMap((group) => group.files.map(fileKey))) : undefined),
    [duplicates],
  )

  if (isPending) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>

  return (
    <>
      <FileBrowser
        files={data ?? []}
        statusOptions={STATUS_OPTIONS}
        duplicateKeys={duplicateKeys}
        header={
          <>
            <LibraryViewSwitch />
            <p className="text-xs text-muted-foreground">{t('library.mediaRightClickHint')}</p>
          </>
        }
        actions={menu.actions}
      />
      {menu.dialog}
    </>
  )
}
