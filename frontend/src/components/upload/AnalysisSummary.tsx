import { CircleCheckIcon, TriangleAlertIcon } from 'lucide-react'

import type { UploadJob } from '@/api/hooks/uploads'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'

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

// Quello che l'analisi locale ha trovato (app/upload_analysis.py): se la
// sorgente è già in seed su un client, o se Radarr/Sonarr dicono che è
// stata scaricata da un tracker. Avvisi, mai blocchi: decide l'utente.
export function AnalysisSummary({ job }: { job: UploadJob }) {
  const analysis = job.analysis as unknown as Analysis | null
  if (!analysis) return null
  const clean = analysis.client_matches.length === 0 && analysis.arr_grabs.length === 0
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('upload.analysis.title')}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <p className="text-muted-foreground">
          {t('upload.analysis.files', { count: analysis.file_count, size: formatBytes(analysis.total_size_bytes) })}
        </p>
        {clean && (
          <p className="flex items-center gap-2">
            <CircleCheckIcon className="size-4 text-emerald-500" />
            {t('upload.analysis.clean')}
          </p>
        )}
        {analysis.arr_grabs.map((grab) => (
          <p key={`${grab.tracker_host}:${grab.torrent_id_remote}`} className="flex items-start gap-2">
            <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <span>
              {t('upload.analysis.grabbed', { tracker: grab.indexer ?? grab.tracker_host, id: grab.torrent_id_remote })}
            </span>
          </p>
        ))}
        {analysis.client_matches.length > 0 && (
          <div className="grid gap-1.5">
            <p className="flex items-start gap-2">
              <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
              {t('upload.analysis.onClient')}
            </p>
            <ul className="grid gap-1 pl-6 text-xs">
              {analysis.client_matches.map((match) => (
                <li key={match.info_hash} className="flex flex-wrap items-center gap-x-2">
                  <span className="font-mono">{match.name}</span>
                  <span className="text-muted-foreground">
                    {[
                      match.client,
                      match.tracker_host,
                      match.match === 'hardlink'
                        ? t('upload.analysis.hardlink')
                        : t('upload.analysis.sameSize', { matched: match.videos_matched, total: match.videos_total }),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
