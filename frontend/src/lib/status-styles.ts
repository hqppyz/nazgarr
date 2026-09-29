// Colori degli stati, uguali in tutta l'interfaccia (badge, pallini, card):
// verde seeding, rosso orfano, viola duplicato, ambra in attesa di
// approvazione, azzurro ignorato (in seed ma non in libreria), grigio
// escluso/non identificato, ardesia fermo nel client o tolto dal client.
// Unica fonte: nessun componente sceglie da sé.
export type StatusKey =
  | 'seeding' | 'orphan' | 'duplicate' | 'review' | 'ignored' | 'excluded' | 'unmatched' | 'failed' | 'stopped'

export const STATUS_STYLES: Record<StatusKey, { dot: string; badge: string; gradient: string }> = {
  seeding: {
    dot: 'bg-emerald-500', gradient: 'from-emerald-500/10',
    badge: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  },
  orphan: { dot: 'bg-red-500', gradient: 'from-red-500/10', badge: 'border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-300' },
  duplicate: {
    dot: 'bg-violet-500', gradient: 'from-violet-500/10',
    badge: 'border-violet-500/40 bg-violet-500/15 text-violet-700 dark:text-violet-300',
  },
  review: { dot: 'bg-amber-500', gradient: 'from-amber-500/10', badge: 'border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300' },
  ignored: { dot: 'bg-sky-500', gradient: 'from-sky-500/10', badge: 'border-sky-500/40 bg-sky-500/15 text-sky-700 dark:text-sky-300' },
  excluded: { dot: 'bg-zinc-400', gradient: 'from-zinc-400/10', badge: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300' },
  unmatched: { dot: 'bg-zinc-400', gradient: 'from-zinc-400/10', badge: 'border-zinc-400/40 bg-zinc-400/15 text-zinc-600 dark:text-zinc-300' },
  failed: { dot: 'bg-red-500', gradient: 'from-red-500/10', badge: 'border-red-500/40 bg-red-500/15 text-red-700 dark:text-red-300' },
  stopped: {
    dot: 'bg-slate-500', gradient: 'from-slate-500/10',
    badge: 'border-slate-500/40 bg-slate-500/15 text-slate-700 dark:text-slate-300',
  },
}

// Tipi di cambiamento per file fra due scansioni (Dashboard, app/file_changes.py):
// i cambi di stato riusano il colore dello stato di arrivo.
export const CHANGE_STYLES: Record<string, { dot: string; badge: string }> = {
  new_media: { dot: 'bg-cyan-500', badge: 'border-cyan-500/40 bg-cyan-500/15 text-cyan-700 dark:text-cyan-300' },
  new_torrent: { dot: 'bg-blue-500', badge: 'border-blue-500/40 bg-blue-500/15 text-blue-700 dark:text-blue-300' },
  removed_media: {
    dot: 'bg-orange-500', badge: 'border-orange-500/40 bg-orange-500/15 text-orange-700 dark:text-orange-300',
  },
  removed_torrent: { dot: 'bg-rose-500', badge: 'border-rose-500/40 bg-rose-500/15 text-rose-700 dark:text-rose-300' },
  now_seeding: STATUS_STYLES.seeding,
  resumed: STATUS_STYLES.seeding,
  now_orphaned: STATUS_STYLES.orphan,
  now_ignored: STATUS_STYLES.ignored,
  stopped: STATUS_STYLES.stopped,
  state_changed: STATUS_STYLES.unmatched,
}

// Categorie della vista Not imported (app/not_imported.py): perché un torrent
// in seed non ha hardlink in libreria.
export const NOT_IMPORTED_STYLES: Record<string, { dot: string; badge: string; gradient: string }> = {
  superseded: STATUS_STYLES.review,
  copy: STATUS_STYLES.duplicate,
  removed: STATUS_STYLES.orphan,
  never_imported: STATUS_STYLES.ignored,
  extras_only: STATUS_STYLES.unmatched,
}

// Stati del backend (app/library.py, seed job) -> stile.
export function statusKeyOf(state: string): StatusKey | null {
  switch (state) {
    case 'seeding':
      return 'seeding'
    case 'orphan_media':
    case 'orphan_torrent':
      return 'orphan'
    case 'ignored':
      return 'ignored'
    case 'unmatched':
      return 'unmatched'
    case 'failed':
      return 'failed'
    case 'removed':
      return 'stopped'
    default:
      return null
  }
}

// Card riassuntive (vista folder e poster): stesso gradiente delle card
// della Dashboard (bg-gradient-to-t … to-card), nel colore dello stato.
export function summaryStyle(value: string): { dot: string; gradient: string } {
  if (value === 'all') return { dot: 'bg-foreground', gradient: 'from-primary/5' }
  if (value === 'duplicates') return STATUS_STYLES.duplicate
  if (value === 'review') return STATUS_STYLES.review
  if (value in NOT_IMPORTED_STYLES) return NOT_IMPORTED_STYLES[value]
  const key = statusKeyOf(value)
  return key ? STATUS_STYLES[key] : { dot: 'bg-muted-foreground', gradient: 'from-muted/40' }
}

