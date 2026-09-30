import { ChevronDownIcon, CircleCheckIcon, TriangleAlertIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import type { UploadJob } from '@/api/hooks/uploads'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import { cn } from '@/lib/utils'

interface ClientMatch {
  client: string | null
  name: string
  info_hash: string
  tracker_host: string | null
  state: string
  match: 'hardlink' | 'same_size'
  videos_matched: number
  videos_total: number
}

interface ArrGrab {
  tracker_host: string
  torrent_id_remote: string
  indexer: string | null
}

interface Analysis {
  total_size_bytes: number
  file_count: number
  client_matches: ClientMatch[]
  arr_grabs: ArrGrab[]
}

function groupBy<T>(items: T[], key: (item: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>()
  for (const item of items) groups.set(key(item), [...(groups.get(key(item)) ?? []), item])
  return [...groups.entries()]
}

// Una riga di riepilogo, con l'elenco completo solo aprendola: una serie
// con tanti episodi darebbe altrimenti decine di righe.
function Recap({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="grid min-w-0 gap-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-w-0 items-start gap-2 text-left text-sm"
      >
        <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronDownIcon className={cn('mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && <ul className="ml-6 grid max-h-48 gap-0.5 overflow-y-auto text-xs">{children}</ul>}
    </div>
  )
}

// Quello che l'analisi locale ha trovato (app/upload_analysis.py): se la
// sorgente è già in seed su un client, o se Radarr/Sonarr dicono che è
// stata scaricata da un tracker. Avvisi, mai blocchi: decide l'utente.
export function AnalysisSummary({ job }: { job: UploadJob }) {
  const analysis = job.analysis as unknown as Analysis | null
  if (!analysis) return null
  const clean = analysis.client_matches.length === 0 && analysis.arr_grabs.length === 0
  const grabs = groupBy(analysis.arr_grabs, (g) => g.indexer ?? g.tracker_host)
  const matches = groupBy(analysis.client_matches, (m) => `${m.client ?? '?'}\u0000${m.tracker_host ?? ''}`)
  return (
    <Card className="min-w-0">
      <CardHeader className="flex flex-row flex-wrap items-baseline justify-between gap-2">
        <CardTitle className="text-base">{t('upload.analysis.title')}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {t('upload.analysis.files', { count: analysis.file_count, size: formatBytes(analysis.total_size_bytes) })}
        </span>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        {clean && (
          <p className="flex items-center gap-2 text-sm">
            <CircleCheckIcon className="size-4 text-emerald-500" />
            {t('upload.analysis.clean')}
          </p>
        )}
        {grabs.map(([tracker, items]) => (
          <Recap key={tracker} summary={t('upload.analysis.grabbedRecap', { tracker, count: items.length })}>
            {items.map((grab) => (
              <li key={grab.torrent_id_remote} className="font-mono text-muted-foreground">
                {grab.tracker_host} · {t('upload.analysis.torrentId', { id: grab.torrent_id_remote })}
              </li>
            ))}
          </Recap>
        ))}
        {matches.map(([key, items]) => {
          const hardlinks = items.filter((m) => m.match === 'hardlink').length
          return (
            <Recap
              key={key}
              summary={t(hardlinks > 0 ? 'upload.analysis.onClientRecapHardlink' : 'upload.analysis.onClientRecap', {
                client: items[0].client ?? '?',
                tracker: items[0].tracker_host ?? t('upload.analysis.noTracker'),
                count: items.length,
                hardlinks,
              })}
            >
              {items.map((match) => (
                <li key={match.info_hash} className="flex min-w-0 gap-2">
                  <span className="truncate font-mono" title={match.name}>{match.name}</span>
                  <span className="shrink-0 text-muted-foreground">
                    {match.match === 'hardlink'
                      ? t('upload.analysis.hardlink')
                      : t('upload.analysis.sameSize', { matched: match.videos_matched, total: match.videos_total })}
                  </span>
                </li>
              ))}
            </Recap>
          )
        })}
      </CardContent>
    </Card>
  )
}
