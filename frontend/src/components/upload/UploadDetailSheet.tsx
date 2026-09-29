import { ExternalLinkIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { posterUrl, useMetadataDetails } from '@/api/hooks/metadata'
import { useUpload, type UploadJob } from '@/api/hooks/uploads'
import { AuthedPoster } from '@/components/AuthedPoster'
import { MediaInfoPreview } from '@/components/upload/MediaInfoPreview'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { UploadEventLog } from '@/components/upload/UploadEventLog'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'
import type { MediaInfoSummary } from '@/lib/mediainfo'
import { parseApiDate } from '@/lib/time'
import { dupeUrl } from '@/lib/upload'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Collapsible>
      <CollapsibleTrigger className="text-sm font-medium hover:underline">{title}</CollapsibleTrigger>
      <CollapsibleContent className="min-w-0 pt-2">{children}</CollapsibleContent>
    </Collapsible>
  )
}

interface Dupe {
  torrent_id_remote: string
  name: string
  verdict: string
}

function Facts({ job }: { job: UploadJob }) {
  const analysis = job.analysis as { total_size_bytes?: number; file_count?: number } | null
  const rows: [string, ReactNode][] = []
  if (job.tmdb_id) rows.push(['TMDB', <a key="tmdb" className="inline-flex items-center gap-1 hover:underline" href={`https://www.themoviedb.org/${job.content_type}/${job.tmdb_id}`} target="_blank" rel="noreferrer">{job.content_type}/{job.tmdb_id}<ExternalLinkIcon className="size-3" /></a>])
  if (job.imdb_id) rows.push(['IMDB', <a key="imdb" className="inline-flex items-center gap-1 hover:underline" href={`https://www.imdb.com/title/${job.imdb_id}/`} target="_blank" rel="noreferrer">{job.imdb_id}<ExternalLinkIcon className="size-3" /></a>])
  if (job.tvdb_id) rows.push(['TVDB', job.tvdb_id])
  if (job.mal_id) rows.push(['MAL', job.mal_id])
  if (job.seasons.length > 0) rows.push([t('upload.history.seasons'), `${job.seasons.join(', ')}${job.episode != null ? ` · E${job.episode}` : ''}`])
  if (analysis?.total_size_bytes != null) rows.push([t('upload.history.size'), `${formatBytes(analysis.total_size_bytes)} · ${t('upload.history.files', { count: analysis.file_count })}`])
  if (job.created_at) rows.push([t('upload.history.created'), parseApiDate(job.created_at).toLocaleString()])
  if (job.finished_at) rows.push([t('upload.history.finished'), parseApiDate(job.finished_at).toLocaleString()])
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 font-mono break-all">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

// Il dettaglio di un upload dallo storico: poster e dati del contenuto, esito
// per tracker con i link (il torrent pubblicato e quelli già trovati sul
// tracker), anteprima MediaInfo; registro, screenshot e descrizioni a scomparsa.
export function UploadDetailSheet({ uploadId, onClose }: { uploadId: number | null; onClose: () => void }) {
  const { data: job } = useUpload(uploadId)
  const details = useMetadataDetails(job?.tmdb_id ? job.content_type : null, job?.tmdb_id ?? null)
  const mediainfo = ((job?.analysis as Record<string, unknown> | null)?.mediainfo ?? null) as MediaInfoSummary | null

  return (
    <Sheet open={uploadId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto sm:max-w-4xl">
        {job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex flex-wrap items-center gap-2 break-words">
                {job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')}
                {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
                <UploadStatusBadge status={job.status} />
              </SheetTitle>
              <SheetDescription className="truncate font-mono text-xs" title={job.relative_path}>
                {job.relative_path}
              </SheetDescription>
            </SheetHeader>
            <div className="grid min-w-0 gap-5 px-4 pb-6">
              <div className="flex min-w-0 gap-4">
                {job.tmdb_id && job.content_type && (
                  <AuthedPoster
                    contentType={job.content_type}
                    tmdbId={job.tmdb_id}
                    hasPoster
                    url={posterUrl({ content_type: job.content_type as 'movie' | 'tv', tmdb_id: job.tmdb_id, poster_path: job.poster_path })}
                    className="aspect-[2/3] w-28 shrink-0 overflow-hidden rounded-md"
                  />
                )}
                <div className="grid min-w-0 content-start gap-2">
                  {details.data?.overview && <p className="line-clamp-4 text-xs leading-relaxed">{details.data.overview}</p>}
                  {details.data && details.data.genres.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {details.data.genres.map((genre) => (
                        <Badge key={genre} variant="secondary">{genre}</Badge>
                      ))}
                    </div>
                  )}
                  <Facts job={job} />
                </div>
              </div>

              <div className="grid min-w-0 gap-2">
                {job.targets.map((target) => {
                  const matches = (target.dupes as unknown as Dupe[]).filter((d) => d.verdict !== 'different')
                  return (
                    <div key={target.id} className="grid min-w-0 gap-1.5 rounded-md border p-3 text-xs">
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-medium">{target.tracker_label}</span>
                        {target.action && <ActionBadge action={target.action} />}
                        <UploadStatusBadge status={target.status} />
                        {target.remote_url && (
                          <a href={target.remote_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs hover:underline">
                            {t('upload.result.openOnTracker')}
                            <ExternalLinkIcon className="size-3" />
                          </a>
                        )}
                      </div>
                      {target.approved_name && <p className="font-mono break-all">{target.approved_name}</p>}
                      {target.info_hash && <p className="truncate font-mono text-muted-foreground">{target.info_hash}</p>}
                      {target.error_message && <p className="text-red-600 dark:text-red-400">{target.error_message}</p>}
                      {matches.length > 0 && (
                        <div className="grid min-w-0 gap-0.5">
                          <span className="text-muted-foreground">{t('upload.history.matchesOnTracker')}</span>
                          {matches.map((d) => {
                            const url = dupeUrl(target, d.torrent_id_remote)
                            return (
                              <span key={d.torrent_id_remote} className="flex min-w-0 items-center gap-2">
                                <Badge variant="outline" className="h-4 px-1 text-[10px]">{t(`upload.dupes.verdict.${d.verdict}`)}</Badge>
                                {url ? (
                                  <a href={url} target="_blank" rel="noreferrer" className="truncate font-mono hover:underline" title={d.name}>{d.name}</a>
                                ) : (
                                  <span className="truncate font-mono" title={d.name}>{d.name}</span>
                                )}
                              </span>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <MediaInfoPreview summary={mediainfo} fullText={job.mediainfo_text} />

              <Section title={t('upload.activity')}>
                <UploadEventLog events={job.events} targets={job.targets} />
              </Section>
              {job.screenshot_urls.length > 0 && (
                <Section title={t('upload.history.screenshots', { count: job.screenshot_urls.length })}>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {job.screenshot_urls.map((url) => (
                      <a key={url} href={url} target="_blank" rel="noreferrer" className="truncate font-mono text-xs hover:underline">
                        {url}
                      </a>
                    ))}
                  </div>
                </Section>
              )}
              {job.targets
                .filter((target) => job.descriptions[target.id])
                .map((target) => (
                  <Section key={target.id} title={t('upload.history.description', { tracker: target.tracker_label })}>
                    <pre className="max-h-80 overflow-auto rounded bg-muted p-2 text-[11px] leading-tight whitespace-pre-wrap">
                      {job.descriptions[target.id]}
                    </pre>
                  </Section>
                ))}
              <Link to={`/upload/${job.id}`} className="text-sm text-primary hover:underline">
                {t('upload.history.openPage')}
              </Link>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
