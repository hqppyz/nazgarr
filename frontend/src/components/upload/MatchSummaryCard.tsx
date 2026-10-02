import { EyeIcon, FileVideoIcon, FolderIcon, Undo2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { posterUrl, useMetadataDetails } from '@/api/hooks/metadata'
import { useRematch, type UploadJob } from '@/api/hooks/uploads'
import { AuthedPoster } from '@/components/AuthedPoster'
import { MetadataLinks } from '@/components/upload/MetadataLinks'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { sourceLabel } from '@/lib/upload'

// Dopo il match: il contenuto confermato. Poster a sinistra; a destra
// titolo, percorso della sorgente, tipo e stato, trama e i link ai servizi.
export function MatchSummaryCard({ job }: { job: UploadJob }) {
  const details = useMetadataDetails(job.tmdb_id ? job.content_type : null, job.tmdb_id ?? null)
  const rematch = useRematch(job.id)
  const autoMatched = job.events?.find((e) => e.code === 'auto_matched')
  return (
    <Card className="min-w-0">
      <CardContent className="flex min-w-0 gap-4">
        {job.tmdb_id && job.content_type ? (
          <AuthedPoster
            contentType={job.content_type}
            tmdbId={job.tmdb_id}
            hasPoster
            url={posterUrl({ content_type: job.content_type as 'movie' | 'tv', tmdb_id: job.tmdb_id, poster_path: job.poster_path })}
            className="aspect-[2/3] w-28 shrink-0 self-start overflow-hidden rounded-md sm:w-36"
          />
        ) : (
          <div className="aspect-[2/3] w-28 shrink-0 rounded-md bg-muted sm:w-36" />
        )}
        {/* In colonna, con i link ai metadati in fondo alla scheda. */}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <h1 className="text-xl leading-tight font-semibold break-words">
            {job.title ?? t('upload.untitled')}
            {job.year && <span className="font-normal text-muted-foreground"> ({job.year})</span>}
          </h1>
          <p className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground" title={job.source_path}>
            {job.is_dir ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
            <span className="truncate">{sourceLabel(job)}</span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
            {job.seasons.length > 0 && (
              <Badge variant="secondary">
                {job.seasons.map((n) => `S${String(n).padStart(2, '0')}`).join(' · ')}
                {job.episode != null && `E${String(job.episode).padStart(2, '0')}`}
              </Badge>
            )}
            <UploadStatusBadge status={job.status} />
            {job.origin === 'watch' && (
              <Badge variant="outline" className="gap-1">
                <EyeIcon className="size-3" />
                {t('upload.watch.badge')}
              </Badge>
            )}
            {autoMatched && (
              <Badge variant="outline" title={t('upload.watch.autoMatchedHelp')}>
                {t('upload.watch.autoMatched', { confidence: Math.round(Number(autoMatched.params?.confidence ?? 0) * 100) })}
              </Badge>
            )}
          </div>
          {details.data?.overview && <p className="line-clamp-3 text-xs leading-relaxed">{details.data.overview}</p>}
          <div className="mt-auto flex flex-wrap items-end justify-between gap-2 pt-2">
            <MetadataLinks job={job} />
            {/* Il rollback del match: si torna a scegliere il contenuto, l'analisi si rifà. */}
            {job.status === 'awaiting_decision' && (
              <Button
                variant="outline"
                size="sm"
                disabled={rematch.isPending}
                onClick={() => rematch.mutate(undefined, { onError: (error) => toast.error(error.message) })}
              >
                <Undo2Icon className="size-4" />
                {t('upload.watch.changeMatch')}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
