import { ExternalLinkIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useUpload } from '@/api/hooks/uploads'
import { UploadEventLog } from '@/components/upload/UploadEventLog'
import { ActionBadge } from '@/components/upload/TrackerCheckCard'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { t } from '@/lib/i18n'
import { formatBytes } from '@/lib/library-filters'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Collapsible>
      <CollapsibleTrigger className="text-sm font-medium hover:underline">{title}</CollapsibleTrigger>
      <CollapsibleContent className="pt-2">{children}</CollapsibleContent>
    </Collapsible>
  )
}

// Il dettaglio di un upload dallo storico: esito per tracker in chiaro, il
// resto (registro, mediainfo, screenshot, descrizioni) a scomparsa.
export function UploadDetailSheet({ uploadId, onClose }: { uploadId: number | null; onClose: () => void }) {
  const { data: job } = useUpload(uploadId)
  const analysis = job?.analysis as { total_size_bytes?: number; file_count?: number } | null | undefined
  return (
    <Sheet open={uploadId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto sm:max-w-2xl">
        {job && (
          <>
            <SheetHeader>
              <SheetTitle className="flex flex-wrap items-center gap-2">
                {job.title ? `${job.title}${job.year ? ` (${job.year})` : ''}` : t('upload.untitled')}
                {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
                <UploadStatusBadge status={job.status} />
              </SheetTitle>
              <SheetDescription className="font-mono text-xs break-all">{job.relative_path}</SheetDescription>
            </SheetHeader>
            <div className="grid gap-5 px-4 pb-6">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                {job.tmdb_id && (
                  <>
                    <dt className="text-muted-foreground">TMDB</dt>
                    <dd className="font-mono">{job.content_type}/{job.tmdb_id}</dd>
                  </>
                )}
                {job.imdb_id && (
                  <>
                    <dt className="text-muted-foreground">IMDB</dt>
                    <dd className="font-mono">{job.imdb_id}</dd>
                  </>
                )}
                {job.seasons.length > 0 && (
                  <>
                    <dt className="text-muted-foreground">{t('upload.history.seasons')}</dt>
                    <dd>{job.seasons.join(', ')}{job.episode != null && ` · E${job.episode}`}</dd>
                  </>
                )}
                {analysis?.total_size_bytes != null && (
                  <>
                    <dt className="text-muted-foreground">{t('upload.history.size')}</dt>
                    <dd>{formatBytes(analysis.total_size_bytes)} · {t('upload.history.files', { count: analysis.file_count })}</dd>
                  </>
                )}
              </dl>

              <div className="grid gap-2">
                {job.targets.map((target) => (
                  <div key={target.id} className="grid gap-1 rounded-md border p-3 text-xs">
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
                    {target.info_hash && <p className="font-mono text-muted-foreground">{target.info_hash}</p>}
                    {target.error_message && <p className="text-red-600 dark:text-red-400">{target.error_message}</p>}
                  </div>
                ))}
              </div>

              <Section title={t('upload.activity')}>
                <UploadEventLog events={job.events} targets={job.targets} />
              </Section>
              {job.screenshot_urls.length > 0 && (
                <Section title={t('upload.history.screenshots', { count: job.screenshot_urls.length })}>
                  <div className="grid grid-cols-2 gap-2">
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
              {job.mediainfo_text && (
                <Section title="Mediainfo">
                  <pre className="max-h-80 overflow-auto rounded bg-muted p-2 text-[11px] leading-tight">{job.mediainfo_text}</pre>
                </Section>
              )}
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
