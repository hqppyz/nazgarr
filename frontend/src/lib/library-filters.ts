import type { TreeFileEntry } from '@/components/FileTree'

// Unica fonte di verità per i filtri delle viste ad albero (Media files /
// Torrent files): toolbar, card riassuntive e tree leggono tutti da qui,
// invece di filtrare ciascuno per conto proprio. Tutto client-side — le
// API restituiscono già l'intero elenco dei file con il loro stato.
export interface LibraryFilters {
  status: string
  showExcluded: boolean
  search: string
  minGb: string
  maxGb: string
}

// Tab speciale "Duplicates" (solo Media files): non è uno stato del file,
// è l'appartenenza a un gruppo di copie (GET /api/library/duplicates).
export const DUPLICATES_STATUS = 'duplicates'

export const DEFAULT_FILTERS: LibraryFilters = {
  status: 'all',
  showExcluded: false,
  search: '',
  minGb: '',
  maxGb: '',
}

export interface StatusOption {
  value: string
  label: string
}

// Unità delle dimensioni (Configuration > Interface): decimali
// (MB, GB, TB — base 1000, il default) o binarie (MiB, GiB, TiB — base
// 1024). Impostata una volta da SizeUnitsSync in AppLayout, letta da
// formatBytes e dai filtri di dimensione: nessun componente deve passarla.
export type SizeUnits = 'decimal' | 'binary'
let sizeUnits: SizeUnits = 'decimal'

export function setSizeUnits(units: SizeUnits) {
  sizeUnits = units
}

export function getSizeUnits(): SizeUnits {
  return sizeUnits
}

// "GB" o "GiB": l'unità dei filtri min/max dimensione.
export function gigabyteLabel(units: SizeUnits = sizeUnits): string {
  return units === 'binary' ? 'GiB' : 'GB'
}

// Chiave di un file fra dischi diversi: lo stesso relative_path può
// esistere su due dischi, mai confonderli.
export function fileKey(file: { disk_id?: number; relative_path: string }): string {
  return `${file.disk_id ?? ''}:${file.relative_path}`
}

function parseGb(value: string): number | null {
  if (value.trim() === '') return null
  const n = Number(value.replace(',', '.'))
  const gigabyte = sizeUnits === 'binary' ? 1024 ** 3 : 1e9
  return Number.isFinite(n) && n >= 0 ? n * gigabyte : null
}

export function filterFiles(
  files: TreeFileEntry[],
  filters: LibraryFilters,
  duplicateKeys?: Set<string>,
): TreeFileEntry[] {
  const search = filters.search.trim().toLowerCase()
  const min = parseGb(filters.minGb)
  const max = parseGb(filters.maxGb)
  return files.filter((f) => {
    if (!filters.showExcluded && f.excluded) return false
    if (filters.status === DUPLICATES_STATUS) {
      if (f.excluded || !duplicateKeys?.has(fileKey(f))) return false
    } else if (filters.status !== 'all' && (f.excluded || f.state !== filters.status)) {
      return false  // un file escluso non ha uno stato: compare solo in "All" con il toggle
    }
    if (search && !f.relative_path.toLowerCase().includes(search)) return false
    if (min !== null && f.size_bytes < min) return false
    if (max !== null && f.size_bytes > max) return false
    return true
  })
}

export function hasActiveSearchFilters(filters: LibraryFilters): boolean {
  return filters.search.trim() !== '' || filters.status === DUPLICATES_STATUS
}

export interface StateSummary {
  count: number
  size: number
}

// I totali riflettono sempre i soli file non esclusi, indipendentemente da
// showExcluded — un file escluso non deve mai "contare", anche mentre
// l'utente lo sta guardando temporaneamente.
export function summarizeByState(
  files: TreeFileEntry[],
  duplicateKeys?: Set<string>,
): Record<string, StateSummary> {
  const summary: Record<string, StateSummary> = { all: { count: 0, size: 0 } }
  for (const f of files) {
    if (f.excluded) continue
    const keys = ['all', f.state]
    if (duplicateKeys?.has(fileKey(f))) keys.push(DUPLICATES_STATUS)
    for (const key of keys) {
      summary[key] ??= { count: 0, size: 0 }
      summary[key].count += 1
      summary[key].size += f.size_bytes
    }
  }
  return summary
}

export function formatBytes(bytes: number, units: SizeUnits = sizeUnits): string {
  const base = units === 'binary' ? 1024 : 1000
  const names = units === 'binary' ? ['KiB', 'MiB', 'GiB', 'TiB', 'PiB'] : ['KB', 'MB', 'GB', 'TB', 'PB']
  if (bytes < base) return `${bytes} B`
  let value = bytes
  let unit = -1
  do {
    value /= base
    unit += 1
  } while (value >= base && unit < names.length - 1)
  return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2)} ${names[unit]}`
}
