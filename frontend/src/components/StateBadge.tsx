import { Badge } from '@/components/ui/badge'
import { STATUS_STYLES, statusKeyOf, type StatusKey } from '@/lib/status-styles'
import { cn } from '@/lib/utils'

// Stati unificati per file, docs/SPEC.md §3 — stessa terminologia di
// nazgarr/library/states.py; orphan_media e orphan_torrent sono entrambi "orphaned"
// per l'utente (il lato è già chiaro dalla vista). Colori da status-styles.
const STATE_LABELS: Record<string, string> = {
  seeding: 'seeding',
  orphan_media: 'orphaned',
  orphan_torrent: 'orphaned',
  ignored: 'not imported',
  unmatched: 'unmatched',
  in_progress: 'in progress',
  removed: 'removed from client',
}

// "compact": dentro le righe delle tabelle ad albero — mono, dimensione
// xxs (token --text-xxs in index.css) e nessun padding verticale, così il
// badge non alza l'altezza della riga. Scritto come text-[length:…] e non
// text-xxs: il merge delle classi (cn) non conosce text-xxs, lo prendeva per
// un colore e scartava quello dello stato (text-emerald-700…).
const COMPACT = 'h-auto py-0 px-1.5 font-mono text-[length:var(--text-xxs)] leading-4'

export function StatusBadge({
  status,
  children,
  compact = false,
}: {
  status: StatusKey
  children: React.ReactNode
  compact?: boolean
}) {
  return (
    <Badge variant="outline" className={cn(STATUS_STYLES[status].badge, compact && COMPACT)}>
      {children}
    </Badge>
  )
}

// Accanto a "seeding": ogni torrent che contiene il file è fermo nel client
// (resta tracciato, ma in quel momento non condivide).
export function StoppedBadge({ compact = false }: { compact?: boolean }) {
  return (
    <StatusBadge status="stopped" compact={compact}>
      stopped
    </StatusBadge>
  )
}

export function StateBadge({ state, compact = false }: { state: string; compact?: boolean }) {
  const key = statusKeyOf(state)
  const label = STATE_LABELS[state] ?? state.replace(/_/g, ' ')
  if (key == null) return <Badge variant="outline" className={cn(compact && COMPACT)}>{label}</Badge>
  return (
    <StatusBadge status={key} compact={compact}>
      {label}
    </StatusBadge>
  )
}
