import { useMemo, useState } from 'react'

import { FileFilterBar } from '@/components/FileFilterBar'
import { FileTree, type TreeFileEntry } from '@/components/FileTree'
import { LibrarySummaryCards } from '@/components/LibrarySummaryCards'
import { Card } from '@/components/ui/card'
import {
  DEFAULT_FILTERS,
  filterFiles,
  hasActiveSearchFilters,
  summarizeByState,
  type LibraryFilters,
  type StatusOption,
} from '@/lib/library-filters'
import { ItemDetailSheet, type OpenItem } from '@/pages/library/ItemDetailSheet'

// Struttura comune a "Media files" e "Torrent files": stesse card, stessa
// toolbar, stesso tree — cambiano solo il dataset e gli stati possibili.
export function FileBrowser({
  files,
  statusOptions,
  duplicateKeys,
  header,
}: {
  files: TreeFileEntry[]
  statusOptions: StatusOption[]
  // Solo Media files: senza, il filtro Duplicates non compare.
  duplicateKeys?: Set<string>
  // Sopra le card di riepilogo, es. il selettore Folder | Poster della libreria.
  header?: React.ReactNode
}) {
  const [filters, setFilters] = useState<LibraryFilters>(DEFAULT_FILTERS)
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
      />
      <Card className="py-0">
        {/* Con una ricerca attiva ogni risultato va reso visibile subito,
            non sepolto in una cartella chiusa. */}
        <FileTree
          files={filtered}
          expandAll={hasActiveSearchFilters(filters)}
          duplicateKeys={duplicateKeys}
          onOpenFile={(file) =>
            file.content_type && file.tmdb_id != null &&
            setOpenItem({ contentType: file.content_type, tmdbId: file.tmdb_id })
          }
        />
      </Card>
      <ItemDetailSheet item={openItem} onClose={() => setOpenItem(null)} />
    </div>
  )
}
