import { ArrowLeftIcon, ExternalLinkIcon, FileVideoIcon, FolderIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { posterUrl, useMetadataDetails } from '@/api/hooks/metadata'
import type { UploadJob } from '@/api/hooks/uploads'
import { AuthedPoster } from '@/components/AuthedPoster'
import { JobActions } from '@/components/upload/JobActions'
import { UploadStatusBadge } from '@/components/upload/UploadStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { t } from '@/lib/i18n'

// Dopo il match: il contenuto confermato. Poster a sinistra; a destra tipo
// e stato, titolo, percorso della sorgente, trama e id.
export function MatchSummaryCard({ job }: { job: UploadJob }) {
  const navigate = useNavigate()
  const details = useMetadataDetails(job.tmdb_id ? job.content_type : null, job.tmdb_id ?? null)
  const tmdbUrl = job.tmdb_id ? `https://www.themoviedb.org/${job.content_type}/${job.tmdb_id}` : null
  return (
    <Card className="h-full min-w-0">
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
        <div className="grid min-w-0 flex-1 content-start gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => navigate('/upload')}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <ArrowLeftIcon className="size-3" />
              {t('upload.backToList')}
            </button>
            <JobActions job={job} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {job.kind && <Badge variant="outline">{t(`upload.kind.${job.kind}`)}</Badge>}
            {job.seasons.length > 0 && (
              <Badge variant="secondary">
                {job.seasons.map((n) => `S${String(n).padStart(2, '0')}`).join(' · ')}
                {job.episode != null && `E${String(job.episode).padStart(2, '0')}`}
              </Badge>
            )}
            <UploadStatusBadge status={job.status} />
          </div>
          <h1 className="text-xl leading-tight font-semibold break-words">
            {job.title ?? t('upload.untitled')}
            {job.year && <span className="font-normal text-muted-foreground"> ({job.year})</span>}
          </h1>
          <p className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground" title={job.source_path}>
            {job.is_dir ? <FolderIcon className="size-3.5 shrink-0" /> : <FileVideoIcon className="size-3.5 shrink-0" />}
            <span className="truncate">{job.relative_path}</span>
          </p>
          {details.data?.overview && <p className="line-clamp-3 text-xs leading-relaxed">{details.data.overview}</p>}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
            {tmdbUrl && (
              <a href={tmdbUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-foreground">
                TMDB {job.tmdb_id}
                <ExternalLinkIcon className="size-3" />
              </a>
            )}
            {job.imdb_id && (
              <a href={`https://www.imdb.com/title/${job.imdb_id}/`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-foreground">
                {job.imdb_id}
                <ExternalLinkIcon className="size-3" />
              </a>
            )}
            {job.tvdb_id && <span>TVDB {job.tvdb_id}</span>}
            {job.mal_id && <span>MAL {job.mal_id}</span>}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
