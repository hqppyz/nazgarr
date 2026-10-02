import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { FileFilterBar } from '@/components/FileFilterBar'
import { FileTree, type TreeFileEntry, type TreeRowActions } from '@/components/FileTree'
import { LibrarySummaryCards } from '@/components/LibrarySummaryCards'
import { PackBar, PackSelectButton } from '@/components/upload/PackBar'
import { Card } from '@/components/ui/card'
import {
  DEFAULT_FILTERS,
  filterFiles,
  hasActiveSearchFilters,
  summarizeByState,
  type LibraryFilters,
  type StatusOption,
} from '@/lib/library-filters'
import { usePackSelection } from '@/lib/pack'
import { ItemDetailSheet, type OpenItem } from '@/pages/library/ItemDetailSheet'

// Struttura comune a "Media files" e "Torrent files": stesse card, stessa
// toolbar, stesso tree — cambiano solo il dataset e gli stati possibili.
export function FileBrowser({
  files,
  statusOptions,
  duplicateKeys,
  header,
  actions,
}: {
  files: TreeFileEntry[]
  statusOptions: StatusOption[]
  // Solo Media files: senza, il filtro Duplicates non compare.
  duplicateKeys?: Set<string>
  // Sopra le card di riepilogo, es. il selettore Folder | Poster della libreria.
  header?: React.ReactNode
  // Azioni a fine riga dell'albero (Torrent files: upload/reseed degli orfani).
  actions?: TreeRowActions
}) {
  // Episodi scelti a mano per un pack (nazgarr/upload_pack.py), anche già in seed.
  const selection = usePackSelection()
  // ?status=… apre la vista già filtrata (link delle card della dashboard),
  // solo se è uno stato offerto da questa vista.
  const [searchParams] = useSearchParams()
  const [filters, setFilters] = useState<LibraryFilters>(() => {
    const status = searchParams.get('status')
    return status && statusOptions.some((o) => o.value === status) ? { ...DEFAULT_FILTERS, status } : DEFAULT_FILTERS
  })
  const [openItem, setOpenItem] = useState<OpenItem | null>(null)

  const summary = useMemo(() => summarizeByState(files, duplicateKeys), [files, duplicateKeys])
  const excludedCount = useMemo(() => files.filter((f) => f.excluded).length, [files])
  const filtered = useMemo(() => filterFiles(files, filters, duplicateKeys), [files, filters, duplicateKeys])

  return (
    <div className="grid gap-4">
      {header}
      <LibrarySummaryCards
        statusOptions={statusOptions}
        summary={summary}
        activeStatus={filters.status}
        onSelect={(status) => setFilters({ ...filters, status })}
      />
      <FileFilterBar
        statusOptions={statusOptions}
        summary={summary}
        excludedCount={excludedCount}
        filters={filters}
        onFiltersChange={setFilters}
        actions={<PackSelectButton selection={selection} />}
      />
      <Card className="py-0">
        {/* Con una ricerca attiva ogni risultato va reso visibile subito,
            non sepolto in una cartella chiusa. */}
        <FileTree
          files={filtered}
          expandAll={hasActiveSearchFilters(filters)}
          duplicateKeys={duplicateKeys}
          actions={actions}
          selection={selection}
          onOpenFile={(file) =>
            file.content_type && file.tmdb_id != null &&
            setOpenItem({ contentType: file.content_type, tmdbId: file.tmdb_id })
          }
        />
      </Card>
      <PackBar selection={selection} />
      <ItemDetailSheet item={openItem} onClose={() => setOpenItem(null)} />
    </div>
  )
}
